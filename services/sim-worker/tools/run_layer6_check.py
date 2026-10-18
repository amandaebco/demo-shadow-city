"""Run the Layer 6 scale + clustering check (5,000 residents, seed 42, no policies/events).

Creates two scenarios sharing pop_s42_n5000 via POST /v1/scenarios, runs both with
Layer 6 clustering (CONTRACT.md v1.7 §4.6), reports wall-clock time and /v1/decide items
sent, and confirms identical ticks, metrics, and per-persona decisions in Firestore.
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
    timeout_sec: int = 1200,
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
            if pop_id:
                print(
                    f"Scenario {scenario_id} ready: status={status}, population_id={pop_id} "
                    f"(elapsed {round(time.time() - start, 1)}s)"
                )
                return str(pop_id)
            if status == "failed":
                raise RuntimeError(
                    f"Scenario {scenario_id} failed during population generation: {data}"
                )
            print(
                f"Waiting for scenario {scenario_id}: status={status}, "
                f"elapsed={round(time.time() - start, 1)}s...",
                flush=True,
            )
        time.sleep(4)
    raise TimeoutError(
        f"Timed out waiting for scenario {scenario_id} population ({expected_size})"
    )


def drain_pubsub_for_scenarios(config: WorkerConfig) -> None:
    """Acknowledge pending scenario-start messages so they don't re-trigger."""
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
            f"metrics/summary mismatch between {scenario_1_id} and {scenario_2_id}!"
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
            f"Expected {total_ticks} ticks, got {len(ticks_1)} for {scenario_1_id} "
            f"and {len(ticks_2)} for {scenario_2_id}"
        )

    for tick in range(total_ticks):
        tid = f"{tick:04d}"
        t1 = {k: v for k, v in ticks_1[tid].items() if k != "scenario_id"}
        t2 = {k: v for k, v in ticks_2[tid].items() if k != "scenario_id"}
        if t1 != t2:
            raise AssertionError(
                f"Tick {tid} mismatch between {scenario_1_id} and {scenario_2_id}!"
            )

    return {
        "ticks_compared": total_ticks,
        "all_ticks_identical": True,
        "metrics_summary_identical": True,
        "citywide": m2.get("citywide"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population-size", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario-1-id", type=str, default=None)
    parser.add_argument("--scenario-2-id", type=str, default=None)
    args = parser.parse_args()

    config = WorkerConfig.from_env()
    runner = SimulationRunner(config=config)

    ensure_pubsub_subscription(config)

    t_pop_start = time.time()
    if args.scenario_1_id:
        s1_id = args.scenario_1_id
        print(f"Using existing Scenario 1: {s1_id}", flush=True)
    else:
        print(
            f"Creating Scenario 1 (seed={args.seed}, population_size={args.population_size}, no policies/events)...",
            flush=True,
        )
        s1_id = create_scenario_via_orchestrator(
            orchestrator_url=config.orchestrator_url,
            name=f"Layer 6 Clustered Baseline Run A (n={args.population_size}, seed={args.seed})",
            seed=args.seed,
            population_size=args.population_size,
            policies=[],
            events=[],
        )
        print(f"Created Scenario 1: {s1_id}", flush=True)
    pop_id = wait_for_population_ready(runner.db, s1_id, args.population_size)
    pop_gen_sec = round(time.time() - t_pop_start, 2)

    if args.scenario_2_id:
        s2_id = args.scenario_2_id
        print(f"Using existing Scenario 2: {s2_id}", flush=True)
    else:
        print(
            f"Creating Scenario 2 (seed={args.seed}, population_size={args.population_size}, no policies/events)...",
            flush=True,
        )
        s2_id = create_scenario_via_orchestrator(
            orchestrator_url=config.orchestrator_url,
            name=f"Layer 6 Clustered Baseline Run B (n={args.population_size}, seed={args.seed})",
            seed=args.seed,
            population_size=args.population_size,
            policies=[],
            events=[],
        )
        print(f"Created Scenario 2: {s2_id}", flush=True)
    wait_for_population_ready(runner.db, s2_id, args.population_size)

    drain_pubsub_for_scenarios(config)

    print(f"\n--- Running Scenario 1 ({s1_id}) with Layer 6 clustering ---", flush=True)
    t0 = time.time()
    res1 = runner.run_scenario(s1_id, use_clustering=True)
    dur1 = round(time.time() - t0, 2)
    print(
        f"Scenario 1 ({s1_id}) completed in {dur1}s | "
        f"/v1/decide items sent: {len(res1.decisions)}",
        flush=True,
    )

    print(f"\n--- Running Scenario 2 ({s2_id}) with Layer 6 clustering ---", flush=True)
    t1 = time.time()
    res2 = runner.run_scenario(s2_id, use_clustering=True)
    dur2 = round(time.time() - t1, 2)
    print(
        f"Scenario 2 ({s2_id}) completed in {dur2}s | "
        f"/v1/decide items sent: {len(res2.decisions)}",
        flush=True,
    )

    # Confirm in-memory persona_decisions and shared_from match
    if res1.persona_decisions != res2.persona_decisions:
        raise AssertionError("persona_decisions mismatch between Run 1 and Run 2!")
    sample_pid = sorted(res1.persona_decisions.keys())[0]
    sample_dec = res1.persona_decisions[sample_pid][0]

    print(f"\n--- Verifying Firestore Determinism ({s1_id} vs {s2_id}) ---", flush=True)
    verification = verify_firestore_determinism(runner.db, s1_id, s2_id)

    decide_items_sent = len(res1.decisions)
    saved_pct = round((1.0 - decide_items_sent / max(1, args.population_size)) * 100.0, 1)

    summary = {
        "seed": args.seed,
        "population_id": pop_id,
        "population_size": args.population_size,
        "population_ready_wait_sec": pop_gen_sec,
        "scenario_1_id": s1_id,
        "scenario_2_id": s2_id,
        "decide_items_sent_per_run": decide_items_sent,
        "model_calls_saved_pct": saved_pct,
        "run_1_wall_clock_sec": dur1,
        "run_2_wall_clock_sec": dur2,
        "persona_decisions_count": len(res1.persona_decisions),
        "sample_decision_shared_from": sample_dec.get("shared_from"),
        **verification,
    }
    print("\n=== LAYER 6 CHECK PASSED ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
