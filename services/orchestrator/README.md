# orchestrator

Track A — FastAPI service for scenario endpoints and Gemini agents (CONTRACT.md §3).

**Layer 0:** only `GET /v1/health` →
`{"status": "ok", "service": "orchestrator", "version": "0.1.0", "project": "<GCP_PROJECT_ID>"}`.
The scenario endpoints and ADK agents arrive in Layer 1.

## Run locally

```bash
cd services/orchestrator
uv venv --python 3.12 && uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/uvicorn app.main:app --reload --port 8080
```

## Deploy

```bash
infra/deploy.sh orchestrator
```

Deployed **public** (`--allow-unauthenticated`) because the frontend calls it directly.
Environment: `GCP_PROJECT_ID`, `GCP_REGION`, `FIRESTORE_DATABASE` (set by the deploy script from `.env`).
