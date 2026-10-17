# system-one

Track A — System One decision endpoint (CONTRACT.md §4).

**Current implementation: rule-based mock** (`decided_by: "rule-fallback"`, `model_version: "rule-mock-v0"`),
running on CPU in `asia-southeast2` until Layer 5, when it is replaced by Gemma on Cloud Run GPU.

## Endpoints

- `GET /v1/health` → `{"status": "ok", "model_version": "rule-mock-v0"}`
- `POST /v1/decide` → body `{"items": [...]}` with 1–256 decision request items (CONTRACT.md §2.3);
  returns response items in the same order. Invalid input returns 400 `INVALID_REQUEST` (CONTRACT.md §7).

## Mock rule (CONTRACT.md §4.4)

For each item, over the options in `options` only:

```
score = time_sensitivity × norm(est_minutes) + cost_sensitivity × norm(cost_idr)
```

- `norm` is min-max normalization across the item's options; if all values are equal they normalize to 0.
- The lowest score wins. Ties go to the option listed first in `options`.
- `probabilities` is one-hot (1.0 for the chosen option). The request carries no seed, so the mock
  does not sample; it is fully deterministic.
- `flooded_on_route` is accepted but not used, since §4.4 only names time and cost.
- `decision_id` is `d_` + the first 12 hex chars of SHA-256(`request_id`), so it is stable across calls.
- Only `question_type: "mode_choice"` is accepted (CONTRACT.md §10.4).

## Run locally

```bash
cd services/system-one
uv venv --python 3.12 && uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/uvicorn app.main:app --reload --port 8080
```

## Deploy

```bash
infra/deploy.sh system-one
```

Deployed **private** (`--no-allow-unauthenticated`). Callers need `roles/run.invoker` and a
Google-signed ID token:

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$SYSTEM_ONE_URL/v1/health"
```

TODO(Layer 4): log every request + response to BigQuery `shadow_city.decisions`.
