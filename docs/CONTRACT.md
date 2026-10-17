# Shadow City — Integration Contract

**Version:** v0.1 (draft, 2026-10-17)
**Status:** Draft — review together, then freeze as v1.0.
**Source of truth for design:** `docs/REFERENCE.md`

This contract defines everything that crosses the boundary between the two tracks:

- **Track A — AI & Backend:** orchestrator, Gemini agents (persona, analyst, verifier), System One (Gemma) endpoint, BigQuery logging, distillation.
- **Track B — Simulation & Frontend:** deterministic simulation engine, workers, Firestore state, map frontend, evidence chain and backtest UI.

If it is not in this file, either track may change it freely. If it is in this file, changes follow the process in section 9.

---

## 1. Conventions

| Item | Rule |
| --- | --- |
| Format | JSON, UTF-8 |
| Field names | `snake_case` |
| IDs | Prefixed strings: `p_` persona, `c_` cluster, `s_` scenario, `d_` decision, `r_` report |
| Timestamps | ISO 8601 UTC, e.g. `2026-10-17T10:50:00Z` |
| Coordinates | WGS84 decimal degrees, `lat` / `lng` |
| Simulation time | 1 tick = 5 simulated minutes. Tick 0 = 05:00 local time. A weekday runs ticks 0–203 (05:00–22:00). |
| Money | Integer Indonesian Rupiah (IDR), field suffix `_idr` |
| Duration | Minutes, field suffix `_min` |
| Probabilities | Floats 0–1, summing to 1 within a decision |
| Randomness | Every scenario has an integer `seed`. Same scenario + same seed = identical results. |

### Enums

```text
mode            : walk | motorcycle | car | transjakarta | krl | mrt | ojol
income_band     : low | lower_middle | middle | upper_middle | high
question_type   : mode_choice | departure_shift | trip_cancel | route_choice
policy_type     : parking_tariff | transit_fare | road_closure
event_type      : flood
scenario_status : queued | generating_population | running | analyzing | completed | failed
decided_by      : gemma-system-one | gemini-system-two | rule-fallback
```

Adding a value to an enum is a **minor** change (section 9). Removing or renaming one is a **breaking** change.

---

## 2. Core schemas

### 2.1 Persona (owner: Track A, reader: Track B)

```json
{
  "persona_id": "p_00421",
  "cluster_id": "c_017",
  "home": {"kelurahan": "Penjaringan", "lat": -6.1214, "lng": 106.7923},
  "work": {"kelurahan": "Setiabudi", "lat": -6.2088, "lng": 106.8302},
  "age": 34,
  "occupation": "office worker",
  "income_band": "middle",
  "vehicles": ["motorcycle"],
  "usual_mode": "motorcycle",
  "usual_departure_tick": 24,
  "cost_sensitivity": 0.7,
  "time_sensitivity": 0.6,
  "profile_summary": "Office worker in Setiabudi, rides a motorcycle, avoids long walks.",
  "memory": []
}
```

- `cost_sensitivity`, `time_sensitivity`: 0–1.
- `memory`: short strings, max 5 items, newest last. Written by Track B during simulation (section 4.3), read by Track A when asking for decisions.
- `usual_departure_tick`: the tick the persona normally leaves home.

### 2.2 Scenario (owner: Track A creates, Track B updates status/progress)

```json
{
  "scenario_id": "s_parking_up_flood_north",
  "name": "Central parking +100% with North Jakarta tidal flood",
  "base_scenario_id": "s_baseline_weekday",
  "seed": 42,
  "population_size": 5000,
  "policies": [
    {"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}
  ],
  "events": [
    {"type": "flood", "area_id": "jakarta_utara", "start_tick": 60, "end_tick": 120, "depth_cm": 40}
  ],
  "status": "running",
  "progress": {"current_tick": 84, "total_ticks": 204},
  "created_at": "2026-10-17T10:50:00Z",
  "updated_at": "2026-10-17T10:53:12Z"
}
```

- `change_ratio`: relative change. `1.0` = +100%, `-0.5` = −50%.
- `zone` and `area_id` refer to polygons defined in `data/zones.geojson` (owner: Track B).
- `base_scenario_id`: `null` for a baseline scenario.

### 2.3 Decision request and response — System One (owner: Track A serves, Track B calls)

**Request item**

```json
{
  "request_id": "q_000981",
  "scenario_id": "s_parking_up_flood_north",
  "tick": 84,
  "persona_id": "p_00421",
  "cluster_id": "c_017",
  "question_type": "mode_choice",
  "options": ["motorcycle", "transjakarta", "krl", "ojol"],
  "context": {
    "persona_summary": "Office worker in Setiabudi, rides a motorcycle, avoids long walks.",
    "cost_sensitivity": 0.7,
    "time_sensitivity": 0.6,
    "memory": ["stuck in flood near Pluit yesterday"],
    "options_detail": {
      "motorcycle":   {"est_minutes": 72, "cost_idr": 30000, "flooded_on_route": true},
      "transjakarta": {"est_minutes": 58, "cost_idr": 3500,  "flooded_on_route": false},
      "krl":          {"est_minutes": 65, "cost_idr": 5000,  "flooded_on_route": false},
      "ojol":         {"est_minutes": 75, "cost_idr": 45000, "flooded_on_route": true}
    },
    "active_policies": ["parking_tariff:central:+100%"],
    "active_events": ["flood:jakarta_utara"]
  }
}
```

- All numbers in `options_detail` are computed by the **simulation engine** (Track B). The model never computes them.
- `options` lists only the choices actually available to this persona at this tick.

**Response item**

```json
{
  "request_id": "q_000981",
  "decision_id": "d_88213",
  "probabilities": {"motorcycle": 0.21, "transjakarta": 0.55, "krl": 0.14, "ojol": 0.10},
  "chosen": "transjakarta",
  "reason_short": "Usual route is flooded and transit is cheaper and faster today.",
  "decided_by": "gemma-system-one",
  "model_version": "gemma-shadowcity-v0",
  "latency_ms": 85
}
```

- `chosen` is sampled from `probabilities` using a deterministic RNG seeded with `seed + tick + persona_id hash`, so results are reproducible.
- `reason_short`: max 140 characters, English. Used in the evidence chain UI.
- Track A logs every request + response to BigQuery (section 6). Track B does not need to log decisions.

### 2.4 Agent state per tick (owner: Track B, reader: frontend)

To keep Firestore documents small, positions are stored as parallel arrays per tick:

```json
{
  "scenario_id": "s_parking_up_flood_north",
  "tick": 84,
  "persona_ids": ["p_00421", "p_00422"],
  "lat": [-6.1502, -6.1931],
  "lng": [106.8011, 106.8240],
  "mode": ["transjakarta", "motorcycle"],
  "status": ["traveling", "at_work"]
}
```

- `status`: `at_home | traveling | at_work | stuck | cancelled`.
- One document per tick. At 5,000 agents this stays well under Firestore's 1 MiB document limit; above ~15,000 agents, split by cluster or kelurahan (to be decided in v1.1).

### 2.5 Scenario metrics (owner: Track B, readers: Track A analyst, frontend)

```json
{
  "scenario_id": "s_parking_up_flood_north",
  "by_kelurahan": [
    {
      "kelurahan": "Penjaringan",
      "avg_travel_min": 64.2,
      "avg_cost_idr": 11800,
      "mode_share": {"motorcycle": 0.38, "transjakarta": 0.31, "krl": 0.12, "car": 0.08, "ojol": 0.09, "walk": 0.02},
      "stuck_count": 41,
      "cancelled_count": 12
    }
  ],
  "by_income_band": [
    {"income_band": "low", "avg_travel_min": 71.5, "avg_cost_idr": 9200, "stuck_count": 88}
  ],
  "citywide": {"avg_travel_min": 58.9, "mode_share": {"motorcycle": 0.41, "transjakarta": 0.27}}
}
```

(`mode_share` values above are format examples only.)

### 2.6 Reports (owner: Track A, reader: frontend)

**Analyst report**

```json
{
  "report_id": "r_analyst_0007",
  "scenario_id": "s_parking_up_flood_north",
  "base_scenario_id": "s_baseline_weekday",
  "headline": "Parking increase shifts commuters to transit, but low-income North Jakarta residents lose the most time during the flood.",
  "winners": ["..."],
  "losers": ["..."],
  "recommendations": ["..."],
  "caveats": ["Synthetic population; directional results only."],
  "generated_by": "gemini-system-two"
}
```

**Verifier report**

```json
{
  "report_id": "r_verifier_0003",
  "scenario_id": "s_baseline_weekday",
  "checks": [
    {"name": "age_distribution_vs_reference", "status": "pass", "detail": "..."},
    {"name": "baseline_mode_share_plausible", "status": "warn", "detail": "..."}
  ],
  "overall": "pass"
}
```

`status`: `pass | warn | fail`.

---

## 3. HTTP API — Orchestrator (owner: Track A, caller: frontend)

Base URL: Cloud Run service `orchestrator`. All responses are JSON. Errors follow section 7.

| Method | Path | Body / Query | Returns |
| --- | --- | --- | --- |
| `POST` | `/v1/scenarios` | Scenario without `scenario_id`, `status`, `progress`, timestamps | `{"scenario_id": "..."}` (status `queued`) |
| `GET` | `/v1/scenarios` | — | List of Scenario |
| `GET` | `/v1/scenarios/{scenario_id}` | — | Scenario |
| `GET` | `/v1/scenarios/{scenario_id}/metrics` | — | Scenario metrics (2.5) |
| `GET` | `/v1/scenarios/{scenario_id}/compare` | `?base={scenario_id}` | `{"base": metrics, "variant": metrics}` |
| `GET` | `/v1/scenarios/{scenario_id}/report` | — | Analyst report |
| `GET` | `/v1/scenarios/{scenario_id}/verification` | — | Verifier report |
| `GET` | `/v1/scenarios/{scenario_id}/personas/{persona_id}/decisions` | — | Ordered list of decision request + response pairs (evidence chain) |
| `GET` | `/v1/personas/{persona_id}` | — | Persona |
| `GET` | `/v1/backtests/{backtest_id}` | — | Backtest result (section 8) |

Live tick data is **not** served over HTTP; the frontend subscribes to Firestore directly (section 5).

---

## 4. HTTP API — System One (owner: Track A, caller: Track B workers)

Base URL: Cloud Run service `system-one`. Service-to-service auth with Google-signed ID tokens (Cloud Run invoker role).

### 4.1 `POST /v1/decide`

```json
{"items": [ /* 1 to 256 decision request items (2.3) */ ]}
```

Response:

```json
{"items": [ /* decision response items, same order as request */ ]}
```

- Max 256 items per call. Track B batches per tick.
- Target latency: p95 under 2 s per batch (to be measured in Layer 5).
- If Gemma is unavailable, Track A falls back to Gemini Flash or a rule, and sets `decided_by` accordingly. Track B does not need to handle the fallback.

### 4.2 `GET /v1/health`

Returns `{"status": "ok", "model_version": "..."}`.

### 4.3 Memory updates

Track B appends memory strings to personas through Firestore (`personas/{persona_id}.memory`), max 5 items. Examples: `"stuck in flood near Pluit yesterday"`, `"transjakarta was crowded this morning"`. Short, factual, English.

### 4.4 Mock for parallel work

Until Layer 5, Track A provides `system-one` with `decided_by: "rule-fallback"`: it picks the option with the lowest weighted score of `time_sensitivity × est_minutes` and `cost_sensitivity × cost_idr` (normalized). Same request/response shape, so Track B can integrate from day one.

---

## 5. Firestore layout

| Path | Owner (writes) | Readers |
| --- | --- | --- |
| `scenarios/{scenario_id}` | A creates; B updates `status`, `progress`, `updated_at` | Frontend, A |
| `scenarios/{scenario_id}/ticks/{tick}` | B | Frontend |
| `scenarios/{scenario_id}/metrics/summary` | B | Frontend, A |
| `personas/{persona_id}` | A creates; B appends `memory` only | Both |
| `reports/{report_id}` | A | Frontend |

Tick document IDs are zero-padded: `0000`, `0001`, …, `0203`.

---

## 6. Pub/Sub topics

| Topic | Publisher | Subscriber | Message |
| --- | --- | --- | --- |
| `scenario-start` | A (after population is ready) | B workers | `{"scenario_id": "...", "seed": 42}` |
| `scenario-completed` | B | A (triggers analyst + verifier) | `{"scenario_id": "...", "status": "completed"}` |
| `scenario-failed` | A or B | Both | `{"scenario_id": "...", "stage": "simulation", "error": {...}}` |

### BigQuery tables (dataset `shadow_city`)

| Table | Owner | Content |
| --- | --- | --- |
| `decisions` | A | One row per decision: request, response, `decided_by`, latency |
| `tick_metrics` | B | Aggregates per scenario, tick, kelurahan |
| `distillation_examples` | A | Gemini teacher decisions used to tune Gemma |
| `backtests` | A | Backtest runs and results |

---

## 7. Errors

```json
{
  "error": {
    "code": "INVALID_SCENARIO",
    "message": "population_size must be between 10 and 20000",
    "details": {"field": "population_size"}
  }
}
```

Codes: `INVALID_REQUEST`, `INVALID_SCENARIO`, `NOT_FOUND`, `MODEL_UNAVAILABLE`, `RATE_LIMITED`, `INTERNAL`. HTTP status matches the meaning (400, 404, 429, 500, 503).

---

## 8. Backtest (shared, owner of result: Track A)

```json
{
  "backtest_id": "b_0001",
  "description": "Direction of transit ridership change on a special-fare day",
  "scenario_id": "s_special_fare_day",
  "base_scenario_id": "s_baseline_weekday",
  "metric": "transit_mode_share_change",
  "simulated_value": null,
  "reference_value": null,
  "reference_source": "TODO: link to published ridership figure",
  "direction_match": null,
  "notes": "Compare direction and rough magnitude only."
}
```

Reference values must come from a cited source; never fill them with guesses.

---

## 9. Change process

| Change type | Examples | Process |
| --- | --- | --- |
| Minor | Add an optional field, add an enum value | Announce in team chat, bump to v1.x, update this file in the same PR |
| Breaking | Rename/remove a field, change a type, change an endpoint | Both members agree first, bump to v2.0, update both tracks in the same PR |

Coding agents must not change this file without explicit human approval.

---

## 10. Open questions (resolve before freezing v1.0)

- [ ] Final list of zones in `data/zones.geojson` (central parking zone boundary, flood areas)
- [ ] Population size for the demo (proposal: 5,000)
- [ ] Gemma model size and Cloud Run GPU region availability
- [ ] Whether `departure_shift` and `trip_cancel` are in scope for the first demo or only `mode_choice`
- [ ] Reference data sources for backtest
