#!/usr/bin/env bash
# Build and run the distillation job on a Cloud Run L4 GPU in Singapore. It costs money while running.
# Usage: infra/run-distill.sh [--yes]   (regenerate services/distill/data first, see its README)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
[[ "${1:-}" == "--yes" ]] && ASSUME_YES=true
load_env

REGION="${GEMMA_REGION:-asia-southeast1}"
[[ -s "$REPO_ROOT/services/distill/data/train.jsonl" ]] || { echo "Missing services/distill/data; run the export first." >&2; exit 1; }
echo "Project: $GCP_PROJECT_ID  Region: $REGION  Job: distill (1x NVIDIA L4)"
confirm "Build and run the GPU job? It is billed while it runs."

gcloud run jobs deploy distill \
  --project="$GCP_PROJECT_ID" --region="$REGION" \
  --source="$REPO_ROOT/services/distill" \
  --service-account="sc-system-one@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --gpu=1 --gpu-type=nvidia-l4 --no-gpu-zonal-redundancy \
  --cpu=8 --memory=32Gi --task-timeout=10800 --max-retries=0 \
  --add-volume=name=models,type=cloud-storage,bucket=vertex-model-garden-public-us,readonly=true \
  --add-volume-mount=volume=models,mount-path=/models \
  --quiet
gcloud run jobs execute distill --project="$GCP_PROJECT_ID" --region="$REGION" --async
