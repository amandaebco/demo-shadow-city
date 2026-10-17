"""Run the Layer 2 two-scenario determinism check against Firestore shadow-city and System One.

Usage:
  python tools/run_determinism_check.py --population-size 50 --seed 42
  python tools/run_determinism_check.py --population-size 1000 --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests
from google.cloud import firestore, pubsub_v1

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_worker.config import TOTAL_TICKS, WorkerConfig
from sim_worker.runner import SimulationRunner, ensure_pubsub_subscription


def create_scenario_via_orchestrator(
    orchestrator_url: str,
    name: str,
    seed: int,
    population_size: int,
    policies: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    payload = {
        "name": name,
        "seed": seed,
        "population_size": population_size,
        "policies": policies,
        "events": events,
    }
    resp = requests.post(
        f"{orchestrator_url}/v1/scenarios",
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data["scenario_id"])


def wait_for_population_ready(
    db: firestore.Client,
    scenario_id: str,
    expected_size: int,
    timeout_sec: int = 900,
) -> str:
    """Wait until Track A's orchestrator finishes generating_population and sets population_id."""
    start = time.time()
    doc_ref = db.collection("scenarios").document(scenario_id)
    while time.time() - start < timeout_sec:
        snap = doc_ref.get()
        if snap.exists:
            data = snap.to_dict() or {}
            status = data.get("status")
            pop_id = data.get("population_id")
            if status == "failed":
                raise RuntimeError(
                    f"Scenario {scenario_id} failed during population generation: {data}"
                )
            if pop_id:
                # Orchestrator sets population_id on the scenario doc only after
                # ensure_population() has finished writing all personas.
                query = db.collection("personas").where(
                    filter=firestore.FieldFilter("population_id", "==", pop_id)
                )
                count = sum(1 for _ in query.stream())
                if count >= expected_size:
                    print(
                        f"Scenario {scenario_id} ready: status={status}, population_id={pop_id} ({count} personas)"
                    )
                    return str(pop_id)
                print(
                    f"Waiting for personas ({count}/{expected_size}) for {pop_id} (status={status})..."
                )
            else:
                print(
                    f"Waiting for scenario {scenario_id}: status={status}, population_id={pop_id}..."
                )
        time.sleep(3)
    raise TimeoutError(
        f"Timed out waiting for scenario {scenario_id} population ({expected_size})"
    )


def drain_pubsub_for_scenarios(config: WorkerConfig, scenario_ids: set[str]) -> None:
    """Acknowledge pending scenario-start messages for the target scenarios so they don't re-trigger."""
    from google.api_core.exceptions import DeadlineExceeded

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
        ack_ids = [msg.ack_id for msg in resp.received_messages]
        if ack_ids:
            subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})


def verify_firestore_determinism(
    db: firestore.Client,
    scenario_1_id: str,
    scenario_2_id: str,
    total_ticks: int = TOTAL_TICKS,
) -> dict[str, Any]:
    """Compare every tick document (0000..0203) and metrics/summary in Firestore."""
    s1_ref = db.collection("scenarios").document(scenario_1_id)
    s2_ref = db.collection("scenarios").document(scenario_2_id)

    m1 = s1_ref.collection("metrics").document("summary").get().to_dict() or {}
    m2 = s2_ref.collection("metrics").document("summary").get().to_dict() or {}

    m1_cmp = {k: v for k, v in m1.items() if k != "scenario_id"}
    m2_cmp = {k: v for k, v in m2.items() if k != "scenario_id"}
    if m1_cmp != m2_cmp:
        raise AssertionError(
            f"metrics/summary mismatch between {scenario_1_id} and {scenario_2_id}!\n"
            f"Run 1: {json.dumps(m1_cmp, sort_keys=True)}\n"
            f"Run 2: {json.dumps(m2_cmp, sort_keys=True)}"
        )

    ticks_1 = {
        doc.id: doc.to_dict() or {}
        for doc in s1_ref.collection("ticks").stream()
    }
    ticks_2 = {
        doc.id: doc.to_dict() or {}
        for doc in s2_ref.collection("ticks").stream()
    }

    if len(ticks_1) != total_ticks or len(ticks_2) != total_ticks:
        raise AssertionError(
            f"Expected {total_ticks} ticks, got {len(ticks_1)} for {scenario_1_id} and {len(ticks_2)} for {scenario_2_id}"
        )

    for tick in range(total_ticks):
        tid = f"{tick:04d}"
        t1 = {k: v for k, v in ticks_1[tid].items() if k != "scenario_id"}
        t2 = {k: v for k, v in ticks_2[tid].items() if k != "scenario_id"}
        if t1 != t2:
            raise AssertionError(f"Tick {tid} mismatch between {scenario_1_id} and {scenario_2_id}!")

    return {
        "ticks_compared": total_ticks,
        "all_ticks_identical": True,
        "metrics_summary_identical": True,
        "citywide": m2.get("citywide"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario-1-id", type=str, default=None)
    parser.add_argument("--scenario-2-id", type=str, default=None)
    args = parser.parse_args()

    config = WorkerConfig.from_env()
    runner = SimulationRunner(config=config)

    policies = [
        {"type": "parking_tariff", "zone": "central", "change_ratio": 1.0},
        {"type": "transit_fare", "zone": "all", "change_ratio": -0.3},
    ]
    events = [
        {
            "type": "flood",
            "area_id": "jakarta_utara",
            "start_tick": 18,
            "end_tick": 72,
            "depth_cm": 40,
        }
    ]

    # Ensure subscription exists before creating scenarios
    ensure_pubsub_subscription(config)

    if args.scenario_1_id:
        s1_id = args.scenario_1_id
        print(f"Using existing Scenario 1: {s1_id}")
    else:
        print(
            f"Creating Scenario 1 (seed={args.seed}, population_size={args.population_size})..."
        )
        s1_id = create_scenario_via_orchestrator(
            orchestrator_url=config.orchestrator_url,
            name=f"Layer 2 Determinism Run A (n={args.population_size}, seed={args.seed})",
            seed=args.seed,
            population_size=args.population_size,
            policies=policies,
            events=events,
        )
        print(f"Created Scenario 1: {s1_id}")
    wait_for_population_ready(runner.db, s1_id, args.population_size)

    if args.scenario_2_id:
        s2_id = args.scenario_2_id
        print(f"Using existing Scenario 2: {s2_id}")
    else:
        print(
            f"Creating Scenario 2 (seed={args.seed}, population_size={args.population_size})..."
        )
        s2_id = create_scenario_via_orchestrator(
            orchestrator_url=config.orchestrator_url,
            name=f"Layer 2 Determinism Run B (n={args.population_size}, seed={args.seed})",
            seed=args.seed,
            population_size=args.population_size,
            policies=policies,
            events=events,
        )
        print(f"Created Scenario 2: {s2_id}")
    wait_for_population_ready(runner.db, s2_id, args.population_size)

    drain_pubsub_for_scenarios(config, {s1_id, s2_id})

    print(f"\n--- Running Scenario 1 ({s1_id}) ---")
    t0 = time.time()
    res1 = runner.run_scenario(s1_id)
    dur1 = round(time.time() - t0, 2)
    print(f"Scenario 1 completed in {dur1}s")

    print(f"\n--- Running Scenario 2 ({s2_id}) ---")
    t1 = time.time()
    res2 = runner.run_scenario(s2_id)
    dur2 = round(time.time() - t1, 2)
    print(f"Scenario 2 completed in {dur2}s")

    print(f"\n--- Verifying Firestore Determinism ({s1_id} vs {s2_id}) ---")
    verification = verify_firestore_determinism(runner.db, s1_id, s2_id)

    # Also summarize how many personas were offered MRT and KRL
    personas = runner.load_personas(runner.load_scenario(s2_id))
    mrt_offered = 0
    krl_offered = 0
    for p in personas:
        mrt_plan = runner.network.evaluate_rail_access(
            "mrt",
            float(p["home"]["lat"]),
            float(p["home"]["lng"]),
            float(p["work"]["lat"]),
            float(p["work"]["lng"]),
        )
        krl_plan = runner.network.evaluate_rail_access(
            "krl",
            float(p["home"]["lat"]),
            float(p["home"]["lng"]),
            float(p["work"]["lat"]),
            float(p["work"]["lng"]),
        )
        if mrt_plan.reachable or p.get("usual_mode") == "mrt":
            mrt_offered += 1
        if krl_plan.reachable or p.get("usual_mode") == "krl":
            krl_offered += 1

    summary = {
        "seed": args.seed,
        "population_size": args.population_size,
        "scenario_1_id": s1_id,
        "scenario_2_id": s2_id,
        "run_1_duration_sec": dur1,
        "run_2_duration_sec": dur2,
        "mrt_offered_count": mrt_offered,
        "krl_offered_count": krl_offered,
        **verification,
    }
    print("\n=== DETERMINISM CHECK PASSED ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

