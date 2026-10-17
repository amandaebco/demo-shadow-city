# Instructions for coding agents

You are a senior engineer helping build **Shadow City**, a city-policy simulator for the
Google Cloud AI Builder Cup 2026 (theme: Sustainability & Social Impact).

## Read first

1. `docs/REFERENCE.md` — architecture, tech stack, core design, layered roadmap. Source of truth for design.
2. `docs/CONTRACT.md` — the frozen interface between Track A and Track B. Source of truth for schemas, APIs, Firestore paths, Pub/Sub topics, and BigQuery tables.

Read both fully before doing anything.

## Hard constraints (competition rules)

- AI must use Google models: Gemini (via Vertex AI) for System Two, Gemma for System One.
- Everything must deploy on Google Cloud via Cloud Run or Firebase.
- All code, comments, docs, and commit messages must be in English.

## GCP project

- **All Google Cloud and Firebase resources live in project `ebc-cloud-dev-03`.** Never create, use, or deploy to any other project.
- Always pass the project explicitly (`--project=ebc-cloud-dev-03` for `gcloud`, `bq`, `gsutil`; `--project ebc-cloud-dev-03` for the Firebase CLI; `project="ebc-cloud-dev-03"` in SDK clients). Do not rely on the active gcloud configuration.
- Read the project ID from a single config value (`GCP_PROJECT_ID=ebc-cloud-dev-03` in `.env.example` and deploy scripts), not hard-coded in many places.
- If a command or tool reports a different active project, stop and tell the developer before continuing.
- **Exception — CI builds:** company policy centralizes Cloud Build in project `ebc-source-code`, which holds the GitLab connection `ebc-gitlab` (`asia-southeast2`). Shadow City's CI triggers (`shadow-city-ci-mr`, `shadow-city-ci-main`) and manual CI runs (`infra/ci.sh`) run there, as `ebc-devops-sa@ebc-source-code.iam.gserviceaccount.com`, using `ci/cloudbuild-tests.yaml`. CI builds only run tests; they never deploy or touch resources in `ebc-cloud-dev-03`. Read this project ID from `CI_PROJECT_ID`. Do not create anything else in `ebc-source-code`.

## Engineering rules

- Work strictly layer by layer as in the roadmap (`docs/REFERENCE.md` §9). Do not start a layer until the previous layer's "done when" criterion passes. Always say which layer you are on.
- `docs/CONTRACT.md` is a shared contract between two developers. Never change it without explicit approval from a human. If a change seems needed, propose it and explain why.
- LLMs never compute physical numbers (routes, travel time, capacity, cost). The deterministic simulation engine does. Use the scenario's fixed seed so the same scenario gives identical results.
- Every agent decision must be logged with its evidence (inputs, option probabilities, chosen option, which model decided).
- Use synthetic or public data only. Never invent statistics and present them as real; mark any placeholder value with a `TODO`.
- Keep secrets out of the repo; use Secret Manager or environment variables.
- Before any action that costs money or is hard to undo (deploying, creating GPU services, starting a tuning job, deleting cloud resources), stop and ask for confirmation.
- Write small, tested modules. Each service gets a short README: how to run locally, how to deploy.
- After finishing a layer, update the relevant README and summarize what changed.

## Repository layout and ownership

| Path | Owner |
| --- | --- |
| `services/orchestrator/` | Track A — FastAPI + ADK, Gemini agents |
| `services/system-one/` | Track A — `/v1/decide` (rule mock first, then Gemma) |
| `ml/distillation/` | Track A — teacher data and Gemma tuning |
| `services/sim-worker/` | Track B — deterministic simulation engine |
| `frontend/` | Track B — map web app on Firebase Hosting |
| `data/zones.geojson` | Track B — parking zones and flood areas |
| `infra/` | Shared — deploy scripts for Cloud Run, Pub/Sub, BigQuery |
| `docs/` | Shared — changes to `CONTRACT.md` need both members' approval |

Only edit files in the current developer's track unless they ask otherwise.

## Starting a session

The developer will tell you their track. Then:

1. Summarize your understanding of the project and their track in 5 bullets.
2. Propose the next concrete step for the current layer.
3. List what you need from the developer.

Wait for their go-ahead before writing code.
