# orchestrator

Track A — FastAPI service for scenarios, personas and Gemini agents (CONTRACT.md §3).

## Endpoints (Layer 1)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/v1/health` | `{"status": "ok", "service": "orchestrator", "version": "..."}` |
| `POST` | `/v1/scenarios` | Returns `201 {"scenario_id": "..."}`, status `queued`; prepares the population in the background |
| `GET` | `/v1/scenarios` | Newest first, max 100 |
| `GET` | `/v1/scenarios/{id}` | Scenario |
| `GET` | `/v1/scenarios/{id}/metrics` | Reads `scenarios/{id}/metrics/summary` written by Track B |
| `GET` | `/v1/personas/{id}` | Persona |

Not yet: `compare`, `report`, `verification` (Layer 3–4), persona decisions (Layer 4), backtests (Layer 7).
Errors follow CONTRACT.md §7; invalid scenario bodies return `INVALID_SCENARIO` with `details.field`.

## Scenario flow

1. `POST /v1/scenarios` writes `scenarios/{id}` with status `queued`.
2. Background: status `generating_population`, then the population for (`seed`, `population_size`)
   is created, or reused if it already exists, and `population_id` is set on the scenario (CONTRACT.md v1.2).
3. Publishes `{"scenario_id", "seed"}` to `scenario-start`. Track B takes over and sets `running`.
4. On failure: status `failed` and a `scenario-failed` message with `stage: "population"`.

## Population (REFERENCE.md §6.1)

- `population_id = pop_s{seed}_n{size}`, persona IDs `p_s{seed}_n{size}_{index:05d}`.
  `cluster_id` is the same per persona until clustering in Layer 6.
- **Deterministic skeleton** from the seed: home and work kelurahan with jittered coordinates, age, income band.
  TODO(data): these are uniform placeholders over a short kelurahan list (`app/kelurahan.py`, approximate
  centroids). Replace them with BPS distributions and OSM centroids before showing results as realistic.
- **Gemini** (`GEMINI_MODEL`) fills in occupation, vehicles, usual mode, departure tick, sensitivities
  and summary, in batches of 25. Values are clamped and made consistent: a persona who usually
  drives owns a car. 50 personas take about 25 s.
- A population is generated once and reused by every scenario with the same seed and size, so a
  baseline and its variant always share identical personas.

## Run locally

```bash
cd services/orchestrator
uv venv --python 3.12 && uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest                         # uses in-memory fakes, no GCP needed
.venv/bin/uvicorn app.main:app --reload --port 8080   # real Firestore/PubSub/Gemini via gcloud ADC
```

## Deploy

```bash
infra/deploy.sh orchestrator
```

Public (`--allow-unauthenticated`), no CPU throttling, runs as `sc-orchestrator`.
Environment: `GCP_PROJECT_ID`, `GCP_REGION`, `FIRESTORE_DATABASE`, `GEMINI_*` from `.env`.
