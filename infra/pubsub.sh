#!/usr/bin/env bash
# Create the Pub/Sub topics from CONTRACT.md §6 (idempotent).
# Usage: infra/pubsub.sh [--yes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
[[ "${1:-}" == "--yes" ]] && ASSUME_YES=true
load_env

topics="scenario-start scenario-completed scenario-failed"
echo "Project: $GCP_PROJECT_ID  Topics: $topics"
confirm "Create missing topics?"
for topic in $topics; do
  if gcloud pubsub topics describe "$topic" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
    echo "exists : $topic"
  else
    gcloud pubsub topics create "$topic" --project="$GCP_PROJECT_ID" \
      --message-storage-policy-allowed-regions="$GCP_REGION"
  fi
done
# Subscriptions belong to the subscriber: Track B subscribes to scenario-start,
# Track A to scenario-completed (Layer 3).
