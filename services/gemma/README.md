# gemma

Track A — Gemma serving for System One (Layer 5, CONTRACT.md §10.3).

Ollama 0.35.1 serving `gemma4:e2b`, `gemma4:e4b` and `gemma3:4b` on Cloud Run with one NVIDIA L4 GPU in
`asia-southeast1` (Singapore), private (ID token). `system-one` calls it with `DECIDER=gemma`;
models are baked into the image.

## Deploy

```bash
infra/deploy-gemma.sh
```

Scales to zero (`--min-instances=0`), so the GPU is billed only while an instance is up. A cold
start loads the model from the image (tens of seconds).

## Call

```bash
URL=$(gcloud run services describe gemma --project=ebc-cloud-dev-03 --region=asia-southeast1 --format='value(status.url)')
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/api/tags"
```
