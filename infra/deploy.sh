#!/usr/bin/env bash
# Deploy Shadow City services to Cloud Run.
#
# Usage: infra/deploy.sh [orchestrator|system-one|all] [--yes]
#
# Reads configuration from .env (falls back to .env.example). Builds from source
# with Cloud Build. Each service runs as its own service account sc-<service>,
# which must exist first (see infra/README.md).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

target="all"
for arg in "$@"; do
  case "$arg" in
    orchestrator|system-one|all) target="$arg" ;;
    --yes|-y) ASSUME_YES=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done
load_env

account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
if [[ -z "$account" ]]; then
  echo "No active gcloud account. Run: gcloud auth login" >&2
  exit 1
fi

case "$target" in
  all) services="orchestrator system-one" ;;
  *) services="$target" ;;
esac

for service in $services; do
  sa="sc-$service@$GCP_PROJECT_ID.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$sa" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
    echo "Service account $sa does not exist. Create it first (infra/README.md)." >&2
    exit 1
  fi
done

common_env="GCP_PROJECT_ID=$GCP_PROJECT_ID,GCP_REGION=$GCP_REGION,FIRESTORE_DATABASE=$FIRESTORE_DATABASE"
gemini_env="GEMINI_LOCATION=${GEMINI_LOCATION:-global},GEMINI_MODEL=${GEMINI_MODEL:?},GEMINI_FALLBACK_MODEL=${GEMINI_FALLBACK_MODEL:-}"

echo "Project : $GCP_PROJECT_ID"
echo "Region  : $GCP_REGION"
echo "Account : $account"
echo "Services: $services"
confirm "Deploy to Cloud Run? This builds images and may incur cost."

deploy_service() {
  local service="$1"
  local flags=()
  case "$service" in
    orchestrator)
      # Public: called by the frontend (CONTRACT.md §3).
      # No CPU throttling: population generation runs after POST /v1/scenarios returns.
      flags=(--allow-unauthenticated --no-cpu-throttling --timeout=300
             --set-env-vars="$common_env,$gemini_env")
      ;;
    system-one)
      # Private: Track B workers call it with ID tokens (CONTRACT.md §4).
      flags=(--no-allow-unauthenticated --timeout=120
             --set-env-vars="$common_env,$gemini_env,DECIDER=${SYSTEM_ONE_DECIDER:-rule},BIGQUERY_DATASET=${BIGQUERY_DATASET:-}")
      ;;
  esac

  echo "==> Deploying $service"
  gcloud run deploy "$service" \
    --project="$GCP_PROJECT_ID" \
    --region="$GCP_REGION" \
    --source="$REPO_ROOT/services/$service" \
    --service-account="sc-$service@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --platform=managed \
    --cpu=1 \
    --memory=512Mi \
    --min-instances=0 \
    --max-instances=2 \
    "${flags[@]}" \
    --quiet

  local url
  url="$(gcloud run services describe "$service" \
    --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format='value(status.url)')"
  echo "==> $service URL: $url"

  echo "==> Health check: $url/v1/health"
  if [[ "$service" == "orchestrator" ]]; then
    curl -fsS "$url/v1/health"
  else
    curl -fsS -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$url/v1/health"
  fi
  echo
}

for service in $services; do
  deploy_service "$service"
done
