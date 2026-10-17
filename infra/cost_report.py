#!/usr/bin/env python3
"""Gemini cost of one scenario, from Cloud Logging.

Sums the usage logged by system-one (decisions), and by the orchestrator
(population generation for the scenario's population_id, and its report).

Usage: infra/cost_report.py SCENARIO_ID [--days 7]
"""

import argparse
import json
import subprocess
import urllib.error
import urllib.request

PROJECT = "ebc-cloud-dev-03"
ORCHESTRATOR = "https://orchestrator-697653429683.asia-southeast2.run.app"


def read_logs(log_filter: str, days: int) -> list[dict]:
    out = subprocess.run(
        ["gcloud", "logging", "read", log_filter, f"--project={PROJECT}", f"--freshness={days}d",
         "--limit=100000", "--format=json"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [entry["jsonPayload"] for entry in json.loads(out or "[]")]


def summarize(label: str, usages: list) -> dict:
    priced = [u for u in usages if u and u.get("cost_usd") is not None]
    return {
        "stage": label,
        "calls": len(usages),
        "no_usage": sum(1 for u in usages if not u),
        "unpriced": sum(1 for u in usages if u and u.get("cost_usd") is None),
        "tokens": sum(u["prompt_tokens"] + u["output_tokens"] + u["thoughts_tokens"] for u in usages if u),
        "cost_usd": sum(u["cost_usd"] for u in priced),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_id")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    try:
        with urllib.request.urlopen(f"{ORCHESTRATOR}/v1/scenarios/{args.scenario_id}") as resp:
            population_id = json.load(resp).get("population_id")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        population_id = None  # Decisions can be logged for IDs that are not stored scenarios.

    service = 'resource.type="cloud_run_revision" AND resource.labels.service_name='
    decisions = read_logs(
        f'{service}"system-one" AND jsonPayload.event="decision" '
        f'AND jsonPayload.request.scenario_id="{args.scenario_id}"', args.days)
    population = read_logs(
        f'{service}"orchestrator" AND jsonPayload.event="gemini_usage" AND jsonPayload.stage="population" '
        f'AND jsonPayload.population_id="{population_id}"', args.days) if population_id else []
    report = read_logs(
        f'{service}"orchestrator" AND jsonPayload.event="gemini_usage" AND jsonPayload.stage="report" '
        f'AND jsonPayload.scenario_id="{args.scenario_id}"', args.days)

    rows = [
        summarize("decisions", [d.get("usage") for d in decisions]),
        summarize("population", [p.get("usage") for p in population]),
        summarize("report", [r.get("usage") for r in report]),
    ]
    print(f"Scenario {args.scenario_id} (population {population_id})")
    print(f"{'stage':12s} {'calls':>6s} {'no usage':>9s} {'unpriced':>9s} {'tokens':>10s} {'cost USD':>10s}")
    for r in rows:
        print(f"{r['stage']:12s} {r['calls']:6d} {r['no_usage']:9d} {r['unpriced']:9d} {r['tokens']:10d} {r['cost_usd']:10.4f}")
    total = sum(r["cost_usd"] for r in rows)
    priced_decisions = rows[0]["calls"] - rows[0]["no_usage"] - rows[0]["unpriced"]
    print(f"{'total':12s} {'':6s} {'':9s} {'':9s} {sum(r['tokens'] for r in rows):10d} {total:10.4f}")
    if priced_decisions:
        decision_cost = rows[0]["cost_usd"] / priced_decisions
        print(f"Average cost per priced decision: ${decision_cost:.6f}")
    print("Calls with no usage were logged before usage tracking, or decided by the rule mock.")
    print("A population is generated once and shared by every scenario with the same seed and size.")


if __name__ == "__main__":
    main()
