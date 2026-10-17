#!/usr/bin/env bash
# Deploy Shadow City services to Cloud Run.
#
# Usage: infra/deploy.sh [orchestrator|system-one|all] [--yes]
#
# Reads GCP_PROJECT_ID, GCP_REGION and FIRESTORE_DATABASE from .env
# (falls back to .env.example). Builds from source with Cloud Build.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The only project Shadow City may use (AGENTS.md). Guards against a wrong .env.
EXPECTED_PROJECT="ebc-cloud-dev-03"

target="all"
assume_yes="false"
for arg in "$@"; do
  case "$arg" in
    orchestrator|system-one|all) target="$arg" ;;
    --yes|-y) assume_yes="true" ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

env_file="$REPO_ROOT/.env"
[[ -f "$env_file" ]] || env_file="$REPO_ROOT/.env.example"
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is not set in $env_file}"
: "${GCP_REGION:?GCP_REGION is not set in $env_file}"
: "${FIRESTORE_DATABASE:?FIRESTORE_DATABASE is not set in $env_file}"

if [[ "$GCP_PROJECT_ID" != "$EXPECTED_PROJECT" ]]; then
  echo "Refusing to deploy: GCP_PROJECT_ID is '$GCP_PROJECT_ID', expected '$EXPECTED_PROJECT'." >&2
  exit 1
fi

account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
if [[ -z "$account" ]]; then
  echo "No active gcloud account. Run: gcloud auth login" >&2
  exit 1
fi

case "$target" in
  all) services=(orchestrator system-one) ;;
  *) services=("$target") ;;
esac

echo "Project : $GCP_PROJECT_ID"
echo "Region  : $GCP_REGION"
echo "Account : $account"
echo "Services: ${services[*]}"
if [[ "$assume_yes" != "true" ]]; then
  read -r -p "Deploy to Cloud Run? This builds images and may incur cost. [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

deploy_service() {
  local service="$1"
  local auth_flag
  case "$service" in
    # Public: called by the frontend (CONTRACT.md §3).
    orchestrator) auth_flag="--allow-unauthenticated" ;;
    # Private: Track B workers call it with ID tokens (CONTRACT.md §4).
    system-one) auth_flag="--no-allow-unauthenticated" ;;
  esac

  echo "==> Deploying $service"
  gcloud run deploy "$service" \
    --project="$GCP_PROJECT_ID" \
    --region="$GCP_REGION" \
    --source="$REPO_ROOT/services/$service" \
    --platform=managed \
    "$auth_flag" \
    --cpu=1 \
    --memory=512Mi \
    --min-instances=0 \
    --max-instances=2 \
    --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,GCP_REGION=$GCP_REGION,FIRESTORE_DATABASE=$FIRESTORE_DATABASE" \
    --quiet

  local url
  url="$(gcloud run services describe "$service" \
    --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format='value(status.url)')"
  echo "==> $service URL: $url"

  echo "==> Health check: $url/v1/health"
  if [[ "$auth_flag" == "--allow-unauthenticated" ]]; then
    curl -fsS "$url/v1/health"
  else
    curl -fsS -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$url/v1/health"
  fi
  echo
}

for service in "${services[@]}"; do
  deploy_service "$service"
done
