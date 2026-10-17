"""CLI entry point for the Shadow City simulation worker (Layer 0 & Layer 1)."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from sim_worker.config import TOTAL_TICKS, WorkerConfig
from sim_worker.engine import run_placeholder_tick_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sim_worker")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shadow City deterministic simulation worker (Track B)."
    )
    parser.add_argument(
        "--scenario-id",
        default="s_layer_1_smoke_test_803984",
        help="Scenario ID to simulate (default: s_layer_1_smoke_test_803984)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic integer seed for placeholder dry-run (default: 42)",
    )
    parser.add_argument(
        "--total-ticks",
        type=int,
        default=TOTAL_TICKS,
        help=f"Number of ticks to run (default: {TOTAL_TICKS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run offline Layer 0 placeholder tick loop without connecting to GCP.",
    )
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Subscribe to Pub/Sub scenario-start and run scenarios as messages arrive.",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="When used with --listen, exit after processing N messages (or first empty pull).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = WorkerConfig.from_env()

    if args.dry_run:
        logger.info(
            "Running offline placeholder tick loop | project=%s firestore_db=%s scenario_id=%s seed=%d total_ticks=%d",
            config.gcp_project_id,
            config.firestore_database,
            args.scenario_id,
            args.seed,
            args.total_ticks,
        )
        states = run_placeholder_tick_loop(
            scenario_id=args.scenario_id,
            seed=args.seed,
            total_ticks=args.total_ticks,
        )
        first = states[0]
        last = states[-1]
        summary = {
            "scenario_id": args.scenario_id,
            "seed": args.seed,
            "status": "completed",
            "progress": {"current_tick": last.tick, "total_ticks": args.total_ticks},
            "first_tick": {"tick_id": first.tick_id, "simulated_time": first.simulated_time},
            "last_tick": {"tick_id": last.tick_id, "simulated_time": last.simulated_time},
            "gcp_project_id": config.gcp_project_id,
            "firestore_database": config.firestore_database,
        }
        print(json.dumps(summary, indent=2))
        return 0

    from sim_worker.runner import SimulationRunner, listen_for_scenarios

    runner = SimulationRunner(config=config)
    if args.listen:
        count = listen_for_scenarios(runner, max_messages=args.max_messages)
        logger.info("Processed %d scenario message(s).", count)
        return 0

    logger.info(
        "Running Layer 2 scenario | project=%s firestore_db=%s scenario_id=%s",
        config.gcp_project_id,
        config.firestore_database,
        args.scenario_id,
    )
    result = runner.run_scenario(args.scenario_id)
    print(
        json.dumps(
            {
                "scenario_id": result.scenario_id,
                "status": "completed",
                "ticks_written": len(result.tick_states),
                "decisions_count": len(result.decisions),
                "citywide": result.metrics_summary.get("citywide"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
