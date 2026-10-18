#!/usr/bin/env bash
# Create the BigQuery dataset and tables from CONTRACT.md §6 (idempotent).
# Usage: infra/bigquery.sh [--yes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
[[ "${1:-}" == "--yes" ]] && ASSUME_YES=true
load_env

DATASET="${BIGQUERY_DATASET:-shadow_city}"
echo "Project: $GCP_PROJECT_ID  Dataset: $DATASET ($GCP_REGION)  Tables: decisions"
confirm "Create the missing dataset/tables?"

if ! bq --project_id="$GCP_PROJECT_ID" show "$DATASET" >/dev/null 2>&1; then
  bq --project_id="$GCP_PROJECT_ID" mk --dataset --location="$GCP_REGION" \
    --description="Shadow City decision log and analytics" "$GCP_PROJECT_ID:$DATASET"
fi
if ! bq --project_id="$GCP_PROJECT_ID" show "$DATASET.decisions" >/dev/null 2>&1; then
  bq --project_id="$GCP_PROJECT_ID" mk --table \
    --time_partitioning_field=logged_at --time_partitioning_type=DAY \
    --clustering_fields=scenario_id,persona_id \
    --description="One row per System One decision (Track A, CONTRACT.md §6)" \
    "$GCP_PROJECT_ID:$DATASET.decisions" "$REPO_ROOT/infra/bigquery/decisions_schema.json"
fi
echo "ok"
# Track B owns tick_metrics; distillation_examples and backtests come with Layers 5 and 7.
