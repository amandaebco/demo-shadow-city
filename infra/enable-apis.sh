#!/usr/bin/env bash
# One-time setup: enable the Google Cloud APIs needed for Layer 0 deploys.
# Usage: infra/enable-apis.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$REPO_ROOT/.env"
[[ -f "$env_file" ]] || env_file="$REPO_ROOT/.env.example"
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

if [[ "${GCP_PROJECT_ID:-}" != "ebc-cloud-dev-03" ]]; then
  echo "Refusing to run: GCP_PROJECT_ID is '${GCP_PROJECT_ID:-}', expected 'ebc-cloud-dev-03'." >&2
  exit 1
fi

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project="$GCP_PROJECT_ID"
