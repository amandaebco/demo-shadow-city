# `sim-worker` — Deterministic Simulation Worker (Track B)

**Current Layer:** Layer 1 — Gemini-only MVP (`docs/REFERENCE.md` §9, `docs/CONTRACT.md` v1.2).

`sim-worker` is the deterministic simulation engine for **Shadow City**. In Layer 1, it loads a scenario and its synthetic population (`population_id`) from the named Firestore database `shadow-city` in `ebc-cloud-dev-03`, computes straight-line distances, travel times, IDR costs, and policy/flood impacts (`options_detail`), batches `mode_choice` requests to Track A's `system-one` service (`POST /v1/decide`), writes interpolated agent trajectories (`scenarios/{id}/ticks/0000..0203`) and `scenarios/{id}/metrics/summary` to Firestore, and publishes completion events to Pub/Sub (`scenario-completed` / `scenario-failed`).

## Directory Structure

```text
services/sim-worker/
├── .env.example           # Environment variable defaults
├── Dockerfile             # Container image for Cloud Run Jobs / Worker
├── pyproject.toml         # Python package metadata & pytest config
├── requirements.txt       # Python dependencies
├── sim_worker/
│   ├── __init__.py
│   ├── config.py          # Enforces ebc-cloud-dev-03 and shadow-city database
│   ├── physics.py         # Haversine distance, zone polygons, options_detail math
│   ├── system_one.py      # Authenticated client for POST /v1/decide (<= 256 batch)
│   ├── engine.py          # Deterministic tick simulation & metrics aggregation
│   ├── runner.py          # Firestore + Pub/Sub scenario lifecycle runner
│   └── main.py            # CLI entry point (--scenario-id, --listen, --dry-run)
└── tests/
    └── test_engine.py     # Unit tests for config, physics, and simulation engine
```

## Configuration

Copy `.env.example` to `.env` if overriding defaults:

- `GCP_PROJECT_ID=ebc-cloud-dev-03` (enforced at startup)
- `FIRESTORE_DATABASE=shadow-city` (enforced at startup)
- `GCP_REGION=asia-southeast2`
- `SYSTEM_ONE_URL=https://system-one-697653429683.asia-southeast2.run.app`
- `ORCHESTRATOR_URL=https://orchestrator-697653429683.asia-southeast2.run.app`
- `PUBSUB_SUBSCRIPTION=scenario-start-sim-worker`

## How to Run Locally

Local runs authenticate with your `gcloud` user credentials (`gcloud auth print-identity-token` for `system-one` and Application Default Credentials for Firestore `shadow-city` and Pub/Sub).

From `services/sim-worker/`:

```bash
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run unit tests (no GCP connection required)
python -m pytest -v

# 4. Run the Layer 1 smoke test scenario against Firestore shadow-city & System One
python -m sim_worker.main --scenario-id s_layer_1_smoke_test_803984

# 5. Listen for incoming Pub/Sub scenario-start messages
python -m sim_worker.main --listen --max-messages 1
```

## How to Deploy (Cloud Run Jobs)

> **Important:** Always run the deployed worker as the dedicated least-privilege service account `sc-sim-worker@ebc-cloud-dev-03.iam.gserviceaccount.com` (`roles/datastore.user`, `roles/pubsub.subscriber`, `roles/pubsub.publisher`, and `roles/run.invoker` on `system-one`). **Never** run the worker as the default compute service account. Confirm with a human before deploying.

```bash
gcloud run jobs deploy sim-worker \
  --project=ebc-cloud-dev-03 \
  --region=asia-southeast2 \
  --service-account=sc-sim-worker@ebc-cloud-dev-03.iam.gserviceaccount.com \
  --source=. \
  --set-env-vars="GCP_PROJECT_ID=ebc-cloud-dev-03,GCP_REGION=asia-southeast2,FIRESTORE_DATABASE=shadow-city,SYSTEM_ONE_URL=https://system-one-697653429683.asia-southeast2.run.app"
```
