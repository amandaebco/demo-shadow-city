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
COND='expression=resource.name=="projects/ebc-cloud-dev-03/databases/shadow-city",title=shadow-city-db-only'
gcloud iam service-accounts create sc-orchestrator --project=$P --display-name="Shadow City orchestrator"
gcloud iam service-accounts create sc-system-one  --project=$P --display-name="Shadow City system-one"
gcloud iam service-accounts create sc-sim-worker  --project=$P --display-name="Shadow City sim-worker"
bind() { gcloud projects add-iam-policy-binding $P --member=serviceAccount:$1@$P.iam.gserviceaccount.com --role=$2 --condition="$3" --quiet >/dev/null; sleep 3; }
bind sc-orchestrator roles/datastore.user "$COND"
bind sc-orchestrator roles/pubsub.publisher None
bind sc-orchestrator roles/aiplatform.user None
bind sc-system-one   roles/datastore.viewer "$COND"
bind sc-system-one   roles/aiplatform.user None
bind sc-sim-worker   roles/datastore.user "$COND"
bind sc-sim-worker   roles/pubsub.subscriber None
bind sc-sim-worker   roles/pubsub.publisher None
gcloud run services add-iam-policy-binding system-one --project=$P --region=asia-southeast2 \
  --member=serviceAccount:sc-sim-worker@$P.iam.gserviceaccount.com --role=roles/run.invoker
```

The `sleep` avoids "concurrent policy changes" errors; rerun a failed line if one still appears.

| Account | Roles | Why |
| --- | --- | --- |
| `sc-orchestrator` | `datastore.user`*, `pubsub.publisher`, `aiplatform.user` | Writes scenarios, personas and reports, publishes scenario events, calls Gemini |
| `sc-system-one` | `datastore.viewer`*, `aiplatform.user` | Reads scenario seeds and personas, calls Gemini |
| `sc-sim-worker` (Track B) | `datastore.user`*, `pubsub.subscriber`, `pubsub.publisher`, `run.invoker` on `system-one` | Runs the simulation |

\* Conditional on `resource.name == "projects/ebc-cloud-dev-03/databases/shadow-city"`, so no
Shadow City account can read or write the project's `(default)` Firestore database.

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

## CI (Cloud Build in `ebc-source-code`)

Company policy centralizes Cloud Build in `ebc-source-code` (AGENTS.md, "Exception — CI builds").
The repo is linked there as `ebc-demo-app-demo-shadow-city` on connection `ebc-gitlab` (`asia-southeast2`).

| Trigger | Fires on | Runs |
| --- | --- | --- |
| `shadow-city-ci-mr` | Merge requests into `main` | `ci/cloudbuild-tests.yaml` |
| `shadow-city-ci-main` | Pushes to `main` | `ci/cloudbuild-tests.yaml` |

Both run as `ebc-devops-sa@ebc-source-code` and only when `services/system-one/**`,
`services/orchestrator/**` or `ci/**` change. Track B adds its steps to `ci/cloudbuild-tests.yaml`
and its paths to the triggers' included files.

Run the same tests on demand against your working tree: `infra/ci.sh`.

## Gemini cost per scenario

Every Gemini call logs its token usage and cost: decisions in `system-one` (in the decision log
entry), population and report generation in the orchestrator (`"event": "gemini_usage"`).
Prices live in `services/*/app/costs.py` with their source.

```bash
infra/cost_report.py s_layer_1_smoke_test_803984
```

Baseline measured on 2026-10-17 (`gemini-3.8-flash`, introductory pricing):

| Item | Tokens | Cost (USD) |
| --- | --- | --- |
| One mode decision | ~1,080 (574 prompt, 86 output, 417 thinking) | ~0.0023 |
| Population of 50 personas (2 calls) | 8,418 | 0.022 |

Thinking tokens are about 40% of a decision's tokens but most of its cost, because they are
billed as output. This is the Gemini-only baseline that Layer 5 (Gemma) is measured against.
