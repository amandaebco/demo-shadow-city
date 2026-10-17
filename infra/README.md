# infra

Shared deploy scripts. Every script reads `GCP_PROJECT_ID` / `GCP_REGION` / `FIRESTORE_DATABASE`
from `.env` (falls back to `.env.example`) and refuses to run against any project other than
`ebc-cloud-dev-03`.

## Prerequisites

1. `gcloud auth login` with an account that has access to `ebc-cloud-dev-03`.
2. gcloud on Python 3.10+. On Python 3.9, `gcloud run deploy` crashes
   (`unsupported operand type(s) for |`). Quick fix: `export CLOUDSDK_PYTHON="$(uv python find 3.12)"`.
3. One-time: `infra/enable-apis.sh` (enables Cloud Run, Cloud Build, Artifact Registry).

## Deploy to Cloud Run

```bash
infra/deploy.sh               # both services, asks for confirmation
infra/deploy.sh system-one    # one service
infra/deploy.sh all --yes     # skip the prompt
```

Builds from source with Cloud Build (`gcloud run deploy --source`), deploys to `GCP_REGION`
with 1 CPU / 512 MiB, 0–2 instances, then curls `/v1/health`.

| Service | Access |
| --- | --- |
| `orchestrator` | Public |
| `system-one` | Private, ID token + `roles/run.invoker` (CONTRACT.md §4) |

The first `--source` deploy creates the Artifact Registry repo `cloud-run-source-deploy` in the region.
If the build fails with a permission error, the Cloud Build / default compute service account may
need `roles/run.builder` (newer projects no longer grant it by default).

TODO: Pub/Sub topics and BigQuery dataset scripts (later layers).

## Current deployment (Layer 0)

| Service | URL |
| --- | --- |
| `orchestrator` | https://orchestrator-697653429683.asia-southeast2.run.app |
| `system-one` | https://system-one-697653429683.asia-southeast2.run.app (private) |
