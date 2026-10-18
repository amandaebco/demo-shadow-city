"""Create and run the Layer 7 Rp1 fare day backtest scenario (CONTRACT.md v1.8 §2.2, §8).

Creates scenario "Rp1 fare day (24 April 2026)" via POST /v1/scenarios with:
- seed: 42
- population_size: 1000 (reuses pop_s42_n1000)
- base_scenario_id: "s_baseline_weekday_ea7247"
- policies: [{"type": "transit_fare", "zone": "all", "change_ratio": -0.9997, "modes": ["transjakarta", "mrt"]}]
- events: []
Runs it WITHOUT clustering (individual decisions for all 1,000 residents, matching the baseline).
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

from sim_worker.config import WorkerConfig
from sim_worker.runner import SimulationRunner, ensure_pubsub_subscription

TRANSIT_MODES = ("transjakarta", "mrt", "krl")


def create_rp1_scenario(orchestrator_url: str) -> str:
    payload: dict[str, Any] = {
        "name": "Rp1 fare day (24 April 2026)",
        "base_scenario_id": "s_baseline_weekday_ea7247",
        "seed": 42,
        "population_size": 1000,
        "policies": [
            {
                "type": "transit_fare",
                "zone": "all",
                "change_ratio": -0.9997,
                "modes": ["transjakarta", "mrt"],
            }
        ],
        "events": [],
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
    timeout_sec: int = 300,
) -> str:
    start = time.time()
    doc_ref = db.collection("scenarios").document(scenario_id)
    while time.time() - start < timeout_sec:
        snap = doc_ref.get()
        if snap.exists:
            data = snap.to_dict() or {}
            pop_id = data.get("population_id")
            if pop_id:
                return str(pop_id)
            if data.get("status") == "failed":
                raise RuntimeError(f"Scenario {scenario_id} failed: {data}")
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for scenario {scenario_id} population_id")


def drain_pubsub(config: WorkerConfig) -> None:
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


def transit_share_pct(metrics: dict[str, Any]) -> float:
    share = (metrics.get("citywide") or {}).get("mode_share") or {}
    return round(sum(float(share.get(m, 0.0)) for m in TRANSIT_MODES) * 100.0, 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-id", type=str, default=None)
    args = parser.parse_args()

    config = WorkerConfig.from_env()
    runner = SimulationRunner(config=config)
    ensure_pubsub_subscription(config)

    if args.scenario_id:
        scenario_id = args.scenario_id
        print(f"Using existing Rp1 fare day scenario: {scenario_id}", flush=True)
    else:
        print("Creating Rp1 fare day (24 April 2026) scenario via POST /v1/scenarios...", flush=True)
        scenario_id = create_rp1_scenario(config.orchestrator_url)
        print(f"Created scenario: {scenario_id}", flush=True)

    pop_id = wait_for_population_ready(runner.db, scenario_id)
    print(f"Population ready: {pop_id}", flush=True)
    drain_pubsub(config)

    print(
        f"\n--- Running {scenario_id} WITHOUT clustering (individual decisions for 1,000 residents) ---",
        flush=True,
    )
    t0 = time.time()
    result = runner.run_scenario(scenario_id, use_clustering=False)
    dur = round(time.time() - t0, 2)

    base_metrics = (
        runner.db.collection("scenarios")
        .document("s_baseline_weekday_ea7247")
        .collection("metrics")
        .document("summary")
        .get()
        .to_dict()
        or {}
    )
    var_metrics = result.metrics_summary

    base_transit = transit_share_pct(base_metrics)
    var_transit = transit_share_pct(var_metrics)
    delta_pp = round(var_transit - base_transit, 1)

    summary = {
        "scenario_id": scenario_id,
        "name": "Rp1 fare day (24 April 2026)",
        "base_scenario_id": "s_baseline_weekday_ea7247",
        "population_id": pop_id,
        "clustering_used": False,
        "decide_items_sent": len(result.decisions),
        "wall_clock_sec": dur,
        "base_transit_share_pct": base_transit,
        "rp1_transit_share_pct": var_transit,
        "simulated_transit_share_change_pp": delta_pp,
        "simulated_direction": "increase" if delta_pp > 0.5 else ("decrease" if delta_pp < -0.5 else "no change"),
        "citywide": var_metrics.get("citywide"),
    }
    print("\n=== RP1 FARE DAY BACKTEST SCENARIO COMPLETED ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
