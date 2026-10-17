# infra

Shared deploy scripts. Every script reads `GCP_PROJECT_ID` / `GCP_REGION` / `FIRESTORE_DATABASE`
from `.env` (falls back to `.env.example`) and refuses to run against any project other than
`ebc-cloud-dev-03`.

## Prerequisites

1. `gcloud auth login` with an account that has access to `ebc-cloud-dev-03`.
2. gcloud on Python 3.10+. On Python 3.9, `gcloud run deploy` crashes
   (`unsupported operand type(s) for |`). Quick fix: `export CLOUDSDK_PYTHON="$(uv python find 3.12)"`.
3. One-time: `infra/enable-apis.sh` (Cloud Run, Cloud Build, Artifact Registry, Vertex AI, Firestore, Pub/Sub, IAM).
4. One-time: `infra/pubsub.sh` creates the topics from CONTRACT.md §6.
5. One-time: runtime service accounts (below). `deploy.sh` refuses to deploy without them.

## Runtime service accounts

Each service runs as its own least-privilege account instead of the default compute
account (which has `roles/editor` and is shared with other apps in the project).
Granting IAM roles is done by a human, not by scripts in this repo:

```bash
P=ebc-cloud-dev-03
gcloud iam service-accounts create sc-orchestrator --project=$P --display-name="Shadow City orchestrator"
gcloud iam service-accounts create sc-system-one  --project=$P --display-name="Shadow City system-one"
for r in roles/datastore.user roles/pubsub.publisher roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding $P --member=serviceAccount:sc-orchestrator@$P.iam.gserviceaccount.com --role=$r --condition=None
done
for r in roles/datastore.viewer roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding $P --member=serviceAccount:sc-system-one@$P.iam.gserviceaccount.com --role=$r --condition=None
done
```

| Account | Roles | Why |
| --- | --- | --- |
| `sc-orchestrator` | `datastore.user`, `pubsub.publisher`, `aiplatform.user` | Writes scenarios and personas, publishes scenario events, calls Gemini |
| `sc-system-one` | `datastore.viewer`, `aiplatform.user` | Reads scenario seeds, calls Gemini |

TODO: `roles/datastore.*` covers every Firestore database in the project, including `(default)`.
Narrow it with an IAM condition on database `shadow-city`.

Track B's worker account also needs `roles/run.invoker` on `system-one`.

## Deploy to Cloud Run

```bash
infra/deploy.sh               # both services, asks for confirmation
infra/deploy.sh system-one    # one service
infra/deploy.sh all --yes     # skip the prompt
```

Builds from source with Cloud Build (`gcloud run deploy --source`), deploys to `GCP_REGION`
with 1 CPU / 512 MiB, 0–2 instances, then curls `/v1/health`. The orchestrator runs with
`--no-cpu-throttling` because population generation continues after `POST /v1/scenarios`
returns; with 0 min instances it only bills while an instance is up.
`system-one` gets `DECIDER=$SYSTEM_ONE_DECIDER` (`gemini` for Layers 1–4).

| Service | Access |
| --- | --- |
| `orchestrator` | Public |
| `system-one` | Private, ID token + `roles/run.invoker` (CONTRACT.md §4) |

The first `--source` deploy creates the Artifact Registry repo `cloud-run-source-deploy` in the region.
If the build fails with a permission error, the Cloud Build / default compute service account may
need `roles/run.builder` (newer projects no longer grant it by default).

TODO: BigQuery dataset script (Layer 4).

## Current deployment (Layer 0)

| Service | URL |
| --- | --- |
| `orchestrator` | https://orchestrator-697653429683.asia-southeast2.run.app |
| `system-one` | https://system-one-697653429683.asia-southeast2.run.app (private) |
