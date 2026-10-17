#!/usr/bin/env bash
# Run the test suite on Cloud Build against the current working tree.
# CI runs in the company Cloud Build project (AGENTS.md, "Exception — CI builds").
# Usage: infra/ci.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_env

if [[ "${CI_PROJECT_ID:-}" != "ebc-source-code" ]]; then
  echo "Refusing to run: CI_PROJECT_ID is '${CI_PROJECT_ID:-}', expected 'ebc-source-code'." >&2
  exit 1
fi

gcloud builds submit "$REPO_ROOT" \
  --project="$CI_PROJECT_ID" \
  --region="${CI_REGION:-asia-southeast2}" \
  --service-account="projects/$CI_PROJECT_ID/serviceAccounts/ebc-devops-sa@$CI_PROJECT_ID.iam.gserviceaccount.com" \
  --config="$REPO_ROOT/ci/cloudbuild-tests.yaml"
