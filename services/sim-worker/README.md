# `sim-worker` — Deterministic Simulation Worker (Track B)

**Current Layer:** Layer 3 & Demo Polish — Policy & flood scenarios + per-persona decision evidence chain (`docs/REFERENCE.md` §9, `docs/CONTRACT.md` v1.5).

`sim-worker` is the deterministic simulation engine for **Shadow City**. It routes agents across an OpenStreetMap road graph of mainland DKI Jakarta (`NetworkX`), gates `mrt` and `krl` availability on real operational OSM rail stations (with walking access/egress and headway wait times), centralizes all model assumptions with explicit source `TODO`s in `sim_worker/assumptions.py`, preserves scenario-scoped persona memory (`scenarios/{id}/memory/{persona_id}` without mutating `personas/{id}.memory`), persists per-persona decision evidence chains (`scenarios/{id}/decisions/{persona_id}` per `CONTRACT.md` v1.5 §4.5), and produces byte-for-byte reproducible requests for Track A's `system-one` `decision_cache` (`POST /v1/decide`).

## Directory Structure

```text
services/sim-worker/
├── .env.example                    # Environment variable defaults
├── Dockerfile                      # Container image for Cloud Run Jobs / Worker
├── pyproject.toml                  # Python package metadata & pytest config
├── requirements.txt                # Python dependencies (pydantic, networkx, firestore, pubsub)
├── sim_worker/
│   ├── __init__.py
│   ├── assumptions.py              # Centralized model assumptions labeled with TODOs
│   ├── config.py                   # Enforces ebc-cloud-dev-03 and shadow-city database
│   ├── data/
│   │   └── jakarta_network.json    # OSM road graph (7,232 nodes, 9,662 edges) + operational MRT/KRL stations
│   ├── road_graph.py               # NetworkX shortest-path router & rail station catchment index
│   ├── physics.py                  # Deterministic travel times, IDR tariffs, flood path checks
│   ├── system_one.py               # Authenticated client for POST /v1/decide (<= 256 batch)
│   ├── engine.py                   # Road-graph tick simulation, decisions log & metrics aggregation
│   ├── runner.py                   # Firestore + Pub/Sub scenario lifecycle runner
│   └── main.py                     # CLI entry point (--scenario-id, --listen, --dry-run)
├── tools/
│   ├── build_network.py            # Extracts OSM road network & operational stations via Overpass API
│   ├── run_determinism_check.py    # Creates and compares two identical scenarios in Firestore
│   └── run_layer3_demos.py         # Creates or re-runs (--rerun) the 3 Layer 3 demo scenarios (A, B, C)
└── tests/
    └── test_engine.py              # Unit tests for config, road graph, station gating, decisions, and determinism
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

# 4. Run a scenario against Firestore shadow-city & System One
python -m sim_worker.main --scenario-id <scenario_id>

# 5. Run the Layer 2 two-scenario determinism check (50 or 1,000 personas)
python tools/run_determinism_check.py --population-size 50 --seed 42
python tools/run_determinism_check.py --population-size 1000 --seed 42

# 6. Listen for incoming Pub/Sub scenario-start messages
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
