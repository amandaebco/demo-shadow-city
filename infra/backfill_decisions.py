#!/usr/bin/env python3
"""Copy decisions logged before BigQuery logging existed into shadow_city.decisions.

Reads system-one's decision log entries from Cloud Logging up to --before (the moment the
BigQuery-writing revision went live), so nothing is copied twice. Entries from before usage
tracking or the cache have those columns empty.

Usage (needs google-cloud-bigquery; system-one's venv has it):
  services/system-one/.venv/bin/python infra/backfill_decisions.py --before 2026-10-18T03:00:00Z [--days 3]
"""

import argparse
import json
import subprocess

from google.cloud import bigquery

PROJECT = "ebc-cloud-dev-03"
TABLE = f"{PROJECT}.shadow_city.decisions"


def read_entries(before: str, days: int) -> list[dict]:
    log_filter = (
        'resource.type="cloud_run_revision" AND resource.labels.service_name="system-one" '
        f'AND jsonPayload.event="decision" AND timestamp<"{before}"'
    )
    out = subprocess.run(
        ["gcloud", "logging", "read", log_filter, f"--project={PROJECT}", f"--freshness={days}d",
         "--limit=200000", "--format=json"],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out or "[]")


def to_row(entry: dict) -> dict:
    payload = entry["jsonPayload"]
    req, resp = payload["request"], payload["response"]
    usage = payload.get("usage") or {}
    return {
        "logged_at": entry["timestamp"],
        "decision_id": resp["decision_id"],
        "request_id": req["request_id"],
        "scenario_id": req["scenario_id"],
        "tick": req["tick"],
        "persona_id": req["persona_id"],
        "cluster_id": req.get("cluster_id"),
        "question_type": req.get("question_type"),
        "options": req.get("options", []),
        "chosen": resp.get("chosen"),
        "probabilities": json.dumps(resp.get("probabilities", {})),
        "reason_short": resp.get("reason_short"),
        "decided_by": resp.get("decided_by"),
        "model_version": resp.get("model_version"),
        "latency_ms": resp.get("latency_ms"),
        "cache": payload.get("cache"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "thoughts_tokens": usage.get("thoughts_tokens"),
        "cost_usd": usage.get("cost_usd"),
        "request": json.dumps(req),
        "response": json.dumps(resp),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, help="RFC 3339 time the BigQuery-writing revision went live")
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()

    rows = [to_row(e) for e in read_entries(args.before, args.days)]
    print(f"{len(rows)} decisions logged before {args.before}")
    client = bigquery.Client(project=PROJECT)
    for start in range(0, len(rows), 500):
        errors = client.insert_rows_json(TABLE, rows[start:start + 500])
        if errors:
            raise SystemExit(f"BigQuery rejected rows: {str(errors)[:500]}")
    print(f"inserted {len(rows)} rows into {TABLE}")


if __name__ == "__main__":
    main()
