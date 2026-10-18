"""Create and run the v2 demo scenarios (A2, B2, C2, D2) on official Dukcapil population data.

All four scenarios use seed=2026, population_size=1000 (pop_s2026_n1000_r2), and run
WITHOUT clustering (individual decisions for all 1,000 residents):
- A2: "Baseline weekday" (no policies, no events, base_scenario_id=None)
- B2: "Central parking +100%" (parking_tariff central +100%, base=A2)
- C2: "Central parking +100% with North Jakarta tidal flood" (parking +100% + flood jakarta_utara ticks 12-72 45cm, base=A2)
- D2: "Rp1 fare day (24 April 2026)" (transit_fare -0.9997 modes=[transjakarta, mrt], base=A2)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import requests
from google.cloud import firestore, pubsub_v1

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim_worker.config import WorkerConfig
from sim_worker.runner import SimulationRunner, ensure_pubsub_subscription


def create_scenario(
    orchestrator_url: str,
    name: str,
    base_scenario_id: str | None,
    seed: int,
    population_size: int,
    policies: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    payload: dict[str, Any] = {
        "name": name,
        "base_scenario_id": base_scenario_id,
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
    return str(resp.json()["scenario_id"])


def wait_for_population_ready(
    db: firestore.Client,
    scenario_id: str,
    timeout_sec: int = 600,
) -> str:
    start = time.time()
    doc_ref = db.collection("scenarios").document(scenario_id)
    while time.time() - start < timeout_sec:
        snap = doc_ref.get()
        if snap.exists:
            data = snap.to_dict() or {}
            pop_id = data.get("population_id")
            status = data.get("status")
            if pop_id:
                print(
                    f"  -> {scenario_id} population ready: {pop_id} (status={status}, {round(time.time() - start, 1)}s)",
                    flush=True,
                )
                return str(pop_id)
            if status == "failed":
                raise RuntimeError(f"Scenario {scenario_id} failed during population generation: {data}")
            print(
                f"  Waiting for {scenario_id} population (status={status}, {round(time.time() - start, 1)}s)...",
                flush=True,
            )
        time.sleep(3)
    raise TimeoutError(f"Timed out waiting for {scenario_id} population_id")


def drain_pubsub(config: WorkerConfig) -> None:
    from google.api_core.exceptions import DeadlineExceeded

    sub_path = ensure_pubsub_subscription(config)
    subscriber = pubsub_v1.SubscriberClient()
    while True:
        try:
            resp = subscriber.pull(
                request={"subscription": sub_path, "max_messages": 10},
                timeout=2.5,
            )
        except DeadlineExceeded:
            break
        if not resp.received_messages:
            break
        ack_ids = [msg.ack_id for msg in resp.received_messages]
        if ack_ids:
            subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})


def main() -> int:
    config = WorkerConfig.from_env()
    runner = SimulationRunner(config=config)
    ensure_pubsub_subscription(config)

    seed = 2026
    pop_size = 1000
    results_summary: dict[str, Any] = {}

    # 1. A2: Baseline weekday
    print("\n=== [A2] Creating 'Baseline weekday' (seed=2026, n=1000) ===", flush=True)
    a2_id = create_scenario(
        orchestrator_url=config.orchestrator_url,
        name="Baseline weekday",
        base_scenario_id=None,
        seed=seed,
        population_size=pop_size,
        policies=[],
        events=[],
    )
    print(f"Created A2: {a2_id}", flush=True)
    pop_id = wait_for_population_ready(runner.db, a2_id)
    drain_pubsub(config)
    t0 = time.time()
    res_a2 = runner.run_scenario(a2_id, use_clustering=False)
    dur_a2 = round(time.time() - t0, 2)
    print(f"[A2 COMPLETED] {a2_id} in {dur_a2}s | citywide={res_a2.metrics_summary.get('citywide')}", flush=True)
    results_summary["A2"] = {
        "scenario_id": a2_id,
        "population_id": pop_id,
        "wall_clock_sec": dur_a2,
        "citywide": res_a2.metrics_summary.get("citywide"),
    }

    # 2. B2: Central parking +100%
    print("\n=== [B2] Creating 'Central parking +100%' (base=A2) ===", flush=True)
    b2_id = create_scenario(
        orchestrator_url=config.orchestrator_url,
        name="Central parking +100%",
        base_scenario_id=a2_id,
        seed=seed,
        population_size=pop_size,
        policies=[{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
        events=[],
    )
    print(f"Created B2: {b2_id}", flush=True)
    wait_for_population_ready(runner.db, b2_id)
    drain_pubsub(config)
    t0 = time.time()
    res_b2 = runner.run_scenario(b2_id, use_clustering=False)
    dur_b2 = round(time.time() - t0, 2)
    print(f"[B2 COMPLETED] {b2_id} in {dur_b2}s | citywide={res_b2.metrics_summary.get('citywide')}", flush=True)
    results_summary["B2"] = {
        "scenario_id": b2_id,
        "wall_clock_sec": dur_b2,
        "citywide": res_b2.metrics_summary.get("citywide"),
    }

    # 3. C2: Central parking +100% with North Jakarta tidal flood
    print("\n=== [C2] Creating 'Central parking +100% with North Jakarta tidal flood' (base=A2) ===", flush=True)
    c2_id = create_scenario(
        orchestrator_url=config.orchestrator_url,
        name="Central parking +100% with North Jakarta tidal flood",
        base_scenario_id=a2_id,
        seed=seed,
        population_size=pop_size,
        policies=[{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
        events=[
            {
                "type": "flood",
                "area_id": "jakarta_utara",
                "start_tick": 12,
                "end_tick": 72,
                "depth_cm": 45,
            }
        ],
    )
    print(f"Created C2: {c2_id}", flush=True)
    wait_for_population_ready(runner.db, c2_id)
    drain_pubsub(config)
    t0 = time.time()
    res_c2 = runner.run_scenario(c2_id, use_clustering=False)
    dur_c2 = round(time.time() - t0, 2)
    print(f"[C2 COMPLETED] {c2_id} in {dur_c2}s | citywide={res_c2.metrics_summary.get('citywide')}", flush=True)
    results_summary["C2"] = {
        "scenario_id": c2_id,
        "wall_clock_sec": dur_c2,
        "citywide": res_c2.metrics_summary.get("citywide"),
    }

    # 4. D2: Rp1 fare day (24 April 2026)
    print("\n=== [D2] Creating 'Rp1 fare day (24 April 2026)' (base=A2) ===", flush=True)
    d2_id = create_scenario(
        orchestrator_url=config.orchestrator_url,
        name="Rp1 fare day (24 April 2026)",
        base_scenario_id=a2_id,
        seed=seed,
        population_size=pop_size,
        policies=[
            {
                "type": "transit_fare",
                "zone": "all",
                "change_ratio": -0.9997,
                "modes": ["transjakarta", "mrt"],
            }
        ],
        events=[],
    )
    print(f"Created D2: {d2_id}", flush=True)
    wait_for_population_ready(runner.db, d2_id)
    drain_pubsub(config)
    t0 = time.time()
    res_d2 = runner.run_scenario(d2_id, use_clustering=False)
    dur_d2 = round(time.time() - t0, 2)
    print(f"[D2 COMPLETED] {d2_id} in {dur_d2}s | citywide={res_d2.metrics_summary.get('citywide')}", flush=True)
    results_summary["D2"] = {
        "scenario_id": d2_id,
        "wall_clock_sec": dur_d2,
        "citywide": res_d2.metrics_summary.get("citywide"),
    }

    print("\n=== ALL FOUR OFFICIAL DATA DEMO SCENARIOS COMPLETED ===")
    print(json.dumps(results_summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
