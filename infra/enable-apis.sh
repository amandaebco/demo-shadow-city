#!/usr/bin/env bash
# One-time setup: enable the Google Cloud APIs Shadow City uses (idempotent).
# Usage: infra/enable-apis.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  iam.googleapis.com \
  --project="$GCP_PROJECT_ID"
