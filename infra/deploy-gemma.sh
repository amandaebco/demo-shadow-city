#!/usr/bin/env bash
# Deploy the Gemma (Ollama) service on a Cloud Run L4 GPU in Singapore. It costs money while running.
# Usage: infra/deploy-gemma.sh [--yes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
[[ "${1:-}" == "--yes" ]] && ASSUME_YES=true
load_env

GPU_REGION="${GEMMA_REGION:-asia-southeast1}"
echo "Project: $GCP_PROJECT_ID  Region: $GPU_REGION  Service: gemma (1x NVIDIA L4, scales to zero)"
confirm "Deploy the GPU service? It is billed while an instance runs."

gcloud run deploy gemma \
  --project="$GCP_PROJECT_ID" \
  --region="$GPU_REGION" \
  --source="$REPO_ROOT/services/gemma" \
  --service-account="sc-system-one@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --no-allow-unauthenticated \
  --gpu=1 --gpu-type=nvidia-l4 --no-gpu-zonal-redundancy \
  --cpu=8 --memory=32Gi --no-cpu-throttling \
  --concurrency=4 --min-instances=0 --max-instances=1 \
  --timeout=600 --port=8080 \
  --quiet
gcloud run services describe gemma --project="$GCP_PROJECT_ID" --region="$GPU_REGION" --format='value(status.url)'
