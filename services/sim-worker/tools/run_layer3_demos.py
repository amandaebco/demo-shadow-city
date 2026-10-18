"""Create and run the three Layer 3 demo scenarios (seed=42, population_size=1000):

A. "Baseline weekday" (no policies, no events, base_scenario_id=None)
B. "Central parking +100%" (parking_tariff central +100%, base_scenario_id=A)
C. "Central parking +100% with North Jakarta tidal flood" (B's policy + flood jakarta_utara, base_scenario_id=A)

Runs A first so A's metrics exist before B and C are created/reported, then triggers
GET /v1/scenarios/{id}/report and GET /v1/scenarios/{id}/compare on the orchestrator.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import requests
from google.api_core.exceptions import DeadlineExceeded
from google.cloud import firestore, pubsub_v1

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_worker.config import WorkerConfig
from sim_worker.runner import SimulationRunner, ensure_pubsub_subscription


def create_scenario(
    orchestrator_url: str,
    name: str,
    seed: int,
    population_size: int,
    policies: list[dict[str, Any]],
    events: list[dict[str, Any]],
    base_scenario_id: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "name": name,
        "seed": seed,
        "population_size": population_size,
        "policies": policies,
        "events": events,
        "base_scenario_id": base_scenario_id,
    }
    resp = requests.post(f"{orchestrator_url}/v1/scenarios", json=payload, timeout=60)
    resp.raise_for_status()
    return str(resp.json()["scenario_id"])


def wait_for_population_ready(
    db: firestore.Client,
    scenario_id: str,
    expected_size: int,
    timeout_sec: int = 300,
) -> str:
    start = time.time()
    doc_ref = db.collection("scenarios").document(scenario_id)
    while time.time() - start < timeout_sec:
        snap = doc_ref.get()
        if snap.exists:
            data = snap.to_dict() or {}
            status = data.get("status")
            pop_id = data.get("population_id")
            if status == "failed":
                raise RuntimeError(f"Scenario {scenario_id} failed: {data}")
            if pop_id:
                print(
                    f"Scenario {scenario_id} population ready: status={status}, population_id={pop_id}"
                )
                return str(pop_id)
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for scenario {scenario_id} population_id")


def drain_pubsub(config: WorkerConfig) -> None:
    sub_path = ensure_pubsub_subscription(config)
    subscriber = pubsub_v1.SubscriberClient()
    while True:
        try:
            resp = subscriber.pull(
                request={"subscription": sub_path, "max_messages": 10},
                timeout=3.0,
            )
        except DeadlineExceeded:
            break
        if not resp.received_messages:
            break
        ack_ids = [m.ack_id for m in resp.received_messages]
        if ack_ids:
            subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})


def ensure_report(orchestrator_url: str, scenario_id: str) -> dict[str, Any]:
    for attempt in range(1, 4):
        resp = requests.get(f"{orchestrator_url}/v1/scenarios/{scenario_id}/report", timeout=120)
        if resp.status_code == 200:
            return resp.json()
        print(f"Report attempt {attempt} for {scenario_id}: HTTP {resp.status_code} ({resp.text[:200]})")
        time.sleep(5)
    raise RuntimeError(f"Failed to fetch report for {scenario_id}")


def rerun_existing_demos(config: WorkerConfig, runner: SimulationRunner) -> int:
    demos = [
        ("A (Baseline weekday)", "s_baseline_weekday_ea7247"),
        ("B (Central parking +100%)", "s_central_parking_100_af902a"),
        ("C (Central parking +100% + North Jakarta flood)", "s_central_parking_100_with_north_jakarta_t_78f06b"),
    ]
    results: dict[str, Any] = {}
    for label, sid in demos:
        print(f"\n=== Re-running {label}: {sid} ===")
        t0 = time.time()
        res = runner.run_scenario(sid)
        dur = round(time.time() - t0, 2)
        print(
            f"Completed {sid} in {dur}s "
            f"(decisions stored: {len(res.persona_decisions)}, "
            f"kelurahan rows: {len(res.metrics_summary.get('by_kelurahan', []))})"
        )
        results[sid] = res

    # Find notable residents who switched mode in Scenario B or Scenario C vs Scenario A
    res_a = results["s_baseline_weekday_ea7247"]
    res_b = results["s_central_parking_100_af902a"]
    res_c = results["s_central_parking_100_with_north_jakarta_t_78f06b"]

    switched_b: list[dict[str, Any]] = []
    switched_c: list[dict[str, Any]] = []
    for pid, decs_a in sorted(res_a.persona_decisions.items()):
        da = decs_a[0]
        db_entry = res_b.persona_decisions[pid][0]
        dc_entry = res_c.persona_decisions[pid][0]
        if db_entry["chosen"] != da["chosen"]:
            switched_b.append(
                {
                    "persona_id": pid,
                    "baseline_chosen": da["chosen"],
                    "variant_b_chosen": db_entry["chosen"],
                    "tick": db_entry["tick"],
                    "reason_short": db_entry["reason_short"],
                    "probabilities": db_entry["probabilities"],
                    "options_detail": db_entry["options_detail"],
                }
            )
        if dc_entry["chosen"] != da["chosen"] or any(
            v.get("flooded_on_route") for v in dc_entry["options_detail"].values()
        ):
            switched_c.append(
                {
                    "persona_id": pid,
                    "baseline_chosen": da["chosen"],
                    "variant_c_chosen": dc_entry["chosen"],
                    "tick": dc_entry["tick"],
                    "reason_short": dc_entry["reason_short"],
                    "probabilities": dc_entry["probabilities"],
                }
            )

    print(f"\n=== NOTABLE RESIDENTS FOR DEMO VIDEO (Scenario B switched: {len(switched_b)}, Scenario C flood/switched: {len(switched_c)}) ===")
    print("Top 5 Scenario B (+100% Central Parking) mode switchers:")
    print(json.dumps(switched_b[:5], indent=2))
    print("\nTop 5 Scenario C (+100% Parking + North Jakarta Flood) affected/switchers:")
    print(json.dumps(switched_c[:5], indent=2))
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create or re-run Layer 3 demo scenarios.")
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Re-run the existing 3 demo scenarios (A, B, C) in-place to populate decisions/ and by_kelurahan.residents.",
    )
    args = parser.parse_args()

    config = WorkerConfig.from_env()
    runner = SimulationRunner(config=config)
    ensure_pubsub_subscription(config)

    if args.rerun:
        return rerun_existing_demos(config, runner)

    seed = 42
    pop_size = 1000

    # --- Scenario A: Baseline weekday ---
    print("\n=== 1. Creating Scenario A: Baseline weekday ===")
    scenario_a_id = create_scenario(
        orchestrator_url=config.orchestrator_url,
        name="Baseline weekday",
        seed=seed,
        population_size=pop_size,
        policies=[],
        events=[],
        base_scenario_id=None,
    )
    print(f"Scenario A ID: {scenario_a_id}")
    wait_for_population_ready(runner.db, scenario_a_id, pop_size)
    drain_pubsub(config)

    t0 = time.time()
    res_a = runner.run_scenario(scenario_a_id)
    dur_a = round(time.time() - t0, 2)
    print(f"Scenario A ({scenario_a_id}) completed in {dur_a}s")
    rep_a = ensure_report(config.orchestrator_url, scenario_a_id)
    print(f"Scenario A report headline: {rep_a.get('headline')}")

    # --- Scenario B: Central parking +100% ---
    print("\n=== 2. Creating Scenario B: Central parking +100% ===")
    policy_b = [{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}]
    scenario_b_id = create_scenario(
        orchestrator_url=config.orchestrator_url,
        name="Central parking +100%",
        seed=seed,
        population_size=pop_size,
        policies=policy_b,
        events=[],
        base_scenario_id=scenario_a_id,
    )
    print(f"Scenario B ID: {scenario_b_id} (base={scenario_a_id})")
    wait_for_population_ready(runner.db, scenario_b_id, pop_size)
    drain_pubsub(config)

    t1 = time.time()
    res_b = runner.run_scenario(scenario_b_id)
    dur_b = round(time.time() - t1, 2)
    print(f"Scenario B ({scenario_b_id}) completed in {dur_b}s")
    rep_b = ensure_report(config.orchestrator_url, scenario_b_id)
    print(f"Scenario B report headline: {rep_b.get('headline')}")

    # --- Scenario C: Central parking +100% with North Jakarta tidal flood ---
    print("\n=== 3. Creating Scenario C: Central parking +100% with North Jakarta tidal flood ===")
    events_c = [
        {
            "type": "flood",
            "area_id": "jakarta_utara",
            "start_tick": 12,
            "end_tick": 72,
            "depth_cm": 45,
        }
    ]
    scenario_c_id = create_scenario(
        orchestrator_url=config.orchestrator_url,
        name="Central parking +100% with North Jakarta tidal flood",
        seed=seed,
        population_size=pop_size,
        policies=policy_b,
        events=events_c,
        base_scenario_id=scenario_a_id,
    )
    print(f"Scenario C ID: {scenario_c_id} (base={scenario_a_id})")
    wait_for_population_ready(runner.db, scenario_c_id, pop_size)
    drain_pubsub(config)

    t2 = time.time()
    res_c = runner.run_scenario(scenario_c_id)
    dur_c = round(time.time() - t2, 2)
    print(f"Scenario C ({scenario_c_id}) completed in {dur_c}s")
    rep_c = ensure_report(config.orchestrator_url, scenario_c_id)
    print(f"Scenario C report headline: {rep_c.get('headline')}")

    # Verify /compare endpoint on B and C
    cmp_b = requests.get(
        f"{config.orchestrator_url}/v1/scenarios/{scenario_b_id}/compare", timeout=30
    ).json()
    cmp_c = requests.get(
        f"{config.orchestrator_url}/v1/scenarios/{scenario_c_id}/compare", timeout=30
    ).json()

    output = {
        "scenario_a": {
            "scenario_id": scenario_a_id,
            "name": "Baseline weekday",
            "duration_sec": dur_a,
            "citywide": res_a.metrics_summary.get("citywide"),
            "headline": rep_a.get("headline"),
        },
        "scenario_b": {
            "scenario_id": scenario_b_id,
            "name": "Central parking +100%",
            "base_scenario_id": scenario_a_id,
            "duration_sec": dur_b,
            "citywide": res_b.metrics_summary.get("citywide"),
            "headline": rep_b.get("headline"),
            "compare_keys": sorted(list(cmp_b.keys())),
        },
        "scenario_c": {
            "scenario_id": scenario_c_id,
            "name": "Central parking +100% with North Jakarta tidal flood",
            "base_scenario_id": scenario_a_id,
            "duration_sec": dur_c,
            "citywide": res_c.metrics_summary.get("citywide"),
            "headline": rep_c.get("headline"),
            "compare_keys": sorted(list(cmp_c.keys())),
        },
    }
    print("\n=== LAYER 3 DEMO SCENARIOS COMPLETED ===")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

