# system-one

Track A — System One decision endpoint (CONTRACT.md §4).

Two deciders, chosen with the `DECIDER` environment variable:

| `DECIDER` | Used in | `decided_by` | `model_version` |
| --- | --- | --- | --- |
| `rule` (default) | Layer 0, tests, local runs | `rule-fallback` | `rule-mock-v0` |
| `gemini` | Layers 1–4 | `gemini-system-two` | Gemini model name, e.g. `gemini-3.8-flash` |

From Layer 5 a Gemma decider on Cloud Run GPU replaces both (`gemma-system-one`).

## Gemini decider

- Gemini sees the persona context and the engine-computed `options_detail`, and returns a
  probability per option plus a short reason (structured output, temperature 0). It never computes numbers.
- Habit context: the decider reads the persona's stable fields (`usual_mode`, `vehicles`,
  `income_band`) from Firestore `personas/{persona_id}` (cached per instance) and adds them to the
  prompt. Gemini is told that the usual mode starts with an advantage, but that people switch when
  another option is clearly better or a policy or event worsens their usual one. On the Layer 1 smoke
  scenario, the favorite equals the usual mode for 43 of 50 personas; without this context, 14 of 50.
  If the persona cannot be read, the prompt simply omits these lines.
- Probabilities are cleaned (negative, non-numeric, unlisted values dropped) and rescaled to sum to 1.
- `chosen` is sampled from them with `random.Random(seed + tick + sha256(persona_id)[:8])`
  (CONTRACT.md §2.3). The seed is read from Firestore `scenarios/{scenario_id}.seed` and cached;
  if the scenario is missing, a hash of `scenario_id` is used and a warning is logged.
- If sampling picks an option other than Gemini's favorite, `reason_short` says so
  (`Sampled ojol (p=0.05); model favored transjakarta (p=0.65). ...`), so the evidence chain stays honest.
- Fallback order: `GEMINI_MODEL` → `GEMINI_FALLBACK_MODEL` → rule mock (`decided_by: rule-fallback`).
- Up to `GEMINI_CONCURRENCY` (default 16) Gemini calls run in parallel per instance.
  One call takes about 5 s, so a 50-item batch takes roughly 15–20 s. The p95 target in §4.1 applies from Layer 5.
- Gemini output varies slightly between runs even at temperature 0, so the same scenario can
  differ between runs. TODO(Layer 2): cache decisions by request content to meet "identical results twice".
- **Decision cache (Layer 2 determinism):** the key is a SHA-256 of model, seed, tick, persona, options and
  the full context (`request_id` and `scenario_id` excluded). A hit returns the stored decision with no model
  call, so replaying a scenario gives identical decisions and costs nothing. Identical requests within one batch
  are decided once. Rule-fallback decisions are never cached. Stored in Firestore `decision_cache/{key}`
  (CONTRACT.md v1.3, Track A only). Disable with `DECISION_CACHE=off`. If the cache cannot be read or
  written, decisions still go through, just without replay.
- Every decision is logged as one structured JSON line (`"event": "decision"`) with the full
  request and response, token usage, and cache status (`hit`, `miss`, `off`), picked up by Cloud Logging.

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
.venv/bin/uvicorn app.main:app --reload --port 8080                  # rule mock
DECIDER=gemini .venv/bin/uvicorn app.main:app --reload --port 8080   # needs gcloud ADC
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

TODO(Layer 4): also write every decision to BigQuery `shadow_city.decisions`.
