# `sim-worker` — Deterministic Simulation Worker (Track B)

**Current Layer:** Layer 0 — Foundation (`docs/REFERENCE.md` §9).

`sim-worker` is the deterministic simulation engine for **Shadow City**. In Layer 0, it provides the project skeleton, configuration guardrails (`GCP_PROJECT_ID=ebc-cloud-dev-03`, `FIRESTORE_DATABASE=shadow-city`), and a deterministic placeholder tick loop (`ticks 0000–0203`, 5 simulated minutes per tick from `05:00` to `21:55` local time) conforming to `docs/CONTRACT.md`.

## Directory Structure

```text
services/sim-worker/
├── .env.example           # Environment variable defaults
├── Dockerfile             # Container image for Cloud Run Jobs
├── pyproject.toml         # Python package metadata & pytest config
├── requirements.txt       # Python dependencies
├── sim_worker/
│   ├── __init__.py
│   ├── config.py          # Enforces ebc-cloud-dev-03 and shadow-city database
│   ├── engine.py          # Deterministic placeholder tick loop (0000-0203)
│   └── main.py            # CLI entry point
└── tests/
    └── test_engine.py     # Unit tests for config and tick loop determinism
```

## Configuration

Copy `.env.example` to `.env` if overriding local paths. Per `AGENTS.md` and `docs/CONTRACT.md`:

- `GCP_PROJECT_ID=ebc-cloud-dev-03` (enforced at startup)
- `FIRESTORE_DATABASE=shadow-city` (named Firestore database in `asia-southeast2`, enforced at startup)
- `GCP_REGION=asia-southeast2`

## How to Run Locally

From `services/sim-worker/`:

```bash
# 1. Create and activate a virtual environment (optional)
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1

# 2. Install test dependencies
pip install -r requirements.txt

# 3. Run the Layer 0 placeholder tick loop
python -m sim_worker.main --scenario-id s_baseline_weekday --seed 42
```

## How to Run Tests

From `services/sim-worker/`:

```bash
python -m pytest -v
```

## How to Deploy (Cloud Run Jobs)

> **Note:** Always confirm before running deployment commands that create or update cloud resources in `ebc-cloud-dev-03`.

```bash
gcloud run jobs deploy sim-worker \
  --project=ebc-cloud-dev-03 \
  --region=asia-southeast2 \
  --source=. \
  --set-env-vars="GCP_PROJECT_ID=ebc-cloud-dev-03,GCP_REGION=asia-southeast2,FIRESTORE_DATABASE=shadow-city"
```
