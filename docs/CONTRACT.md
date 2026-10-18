# Shadow City — Integration Contract

**Version:** v1.7 (frozen, 2026-10-18) — v1.1 adds the named Firestore database `shadow-city`; v1.2 adds the optional `population_id` field (2.1, 2.2) and clarifies the pre-Layer-5 System One decider (10.3); v1.3 adds the Track A-only `decision_cache` collection (5); v1.4 makes memory produced during a scenario scenario-scoped (2.1, 4.3, 5); v1.5 adds per-persona decision records for the evidence chain (4.5, 5); v1.6 moves the Gemma GPU to `asia-southeast1` and names the models (10.3); v1.7 adds persona clusters that share decisions (2.1, 4.6)
**Status:** Frozen. Changes follow section 9.
**GCP project:** `ebc-cloud-dev-03`
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
| Regions | Cloud Run services, Firestore, BigQuery, Pub/Sub: `asia-southeast2` (Jakarta). GPU service `system-one` (Gemma): `us-central1`. Gemini calls: Vertex AI in the nearest supported region. See section 10. |

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
  "population_id": "pop_s42_n5000",
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
- `cluster_id` and `is_cluster_representative` (added in v1.7): residents with similar profiles share a cluster; exactly one member per cluster is its representative. Set by Track A (4.6).
- `population_id` (optional, added in v1.2): the population this persona belongs to. Track B loads a scenario's personas by querying `personas` where `population_id` equals the scenario's `population_id`.
- `memory`: short strings, max 5 items, newest last. The persona's starting memory for every scenario; not changed during simulation (section 4.3).
- `usual_departure_tick`: the tick the persona normally leaves home.

### 2.2 Scenario (owner: Track A creates, Track B updates status/progress)

```json
{
  "scenario_id": "s_parking_up_flood_north",
  "name": "Central parking +100% with North Jakarta tidal flood",
  "base_scenario_id": "s_baseline_weekday",
  "seed": 42,
  "population_size": 5000,
  "population_id": "pop_s42_n5000",
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
- `population_id` (optional, added in v1.2): set by Track A when the population is ready, before `scenario-start` is published. Scenarios with the same `seed` and `population_size` share one population, so a baseline and its variant use identical personas.

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

Memory produced during a scenario belongs to that scenario only, so that two runs of the same scenario start from the same state and replay identically (Layer 2).

- Each scenario starts from the persona's stored `personas/{persona_id}.memory`. Neither track changes that field during simulation.
- Track B keeps the memory produced during the scenario in its own per-scenario state, max 5 items, newest last, and sends it in each decision request's `context.memory`.
- Track B may persist it at `scenarios/{scenario_id}/memory/{persona_id}` as `{"persona_id": "...", "memory": [...]}` for the evidence chain.
- Examples: `"stuck in flood near Pluit yesterday"`, `"transjakarta was crowded this morning"`. Short, factual, English.

### 4.4 Mock for parallel work

Until Layer 5, Track A provides `system-one` with `decided_by: "rule-fallback"`: it picks the option with the lowest weighted score of `time_sensitivity × est_minutes` and `cost_sensitivity × cost_idr` (normalized). Same request/response shape, so Track B can integrate from day one.

---

### 4.5 Decision records (evidence chain)

The worker stores every decision it received for a persona in a scenario, so the frontend can show why a resident chose a mode:

```json
{
  "persona_id": "p_s42_n1000_00421",
  "decisions": [
    {
      "tick": 24,
      "options_detail": {"motorcycle": {"est_minutes": 72, "cost_idr": 30000, "flooded_on_route": true}},
      "probabilities": {"motorcycle": 0.21, "transjakarta": 0.55},
      "chosen": "transjakarta",
      "reason_short": "Usual route is flooded and transit is cheaper and faster today.",
      "decided_by": "gemini-system-two"
    }
  ]
}
```

- Path: `scenarios/{scenario_id}/decisions/{persona_id}`, written by Track B, read by the frontend and Track A.
- Values are copied from the decision request (2.3, `context.options_detail`) and response (2.3), ordered by tick.
- This is the Firestore copy for the UI; the full decision log stays with Track A (2.3, 6).

### 4.6 Clusters share decisions (Layer 6)

To scale to thousands of residents, Track B asks System One once per cluster instead of once per resident.

1. At each decision point (tick), split a cluster's members by their flood signature: the set of options whose `flooded_on_route` is true for that member. Without an active flood every cluster is one group.
2. Send one decision request per group, built from the context of the cluster representative if it is in the group, otherwise of the member with the lowest `persona_id`.
3. Each member samples its own `chosen` from the returned `probabilities`, restricted to the options available to that member and rescaled to sum to 1, with the RNG seeded by `seed + tick + persona_id hash` of the member (as in 2.3). Each member's travel uses its own `options_detail`.
4. A member's decision record (4.5) copies the shared `probabilities`, `reason_short` and `decided_by`, its own `chosen` and `options_detail`, and adds `"shared_from": "<persona_id whose request was sent>"`.

Measured on the 1,000-resident demo population (`ml/distillation/README.md`): 106 clusters, so 84–89% fewer model calls; members' own decisions match their group's in 89% (baseline), 79% (parking +100%) and 75% (parking + flood) of cases, against 19–25% for random groups of the same sizes.

## 5. Firestore layout

All paths below live in the **named Firestore database `shadow-city`** (Native mode, `asia-southeast2`) in project `ebc-cloud-dev-03`. Never write to the project's `(default)` database; it predates this project and may be used by other applications. Every client must select the database explicitly (for example `firestore.Client(project="ebc-cloud-dev-03", database="shadow-city")` in Python, `getFirestore(app, "shadow-city")` in the web SDK), read from the config value `FIRESTORE_DATABASE=shadow-city`.

| Path | Owner (writes) | Readers |
| --- | --- | --- |
| `scenarios/{scenario_id}` | A creates; B updates `status`, `progress`, `updated_at` | Frontend, A |
| `scenarios/{scenario_id}/ticks/{tick}` | B | Frontend |
| `scenarios/{scenario_id}/metrics/summary` | B | Frontend, A |
| `personas/{persona_id}` | A | Both |
| `scenarios/{scenario_id}/memory/{persona_id}` | B (optional, 4.3) | Frontend, A |
| `scenarios/{scenario_id}/decisions/{persona_id}` | B (4.5) | Frontend, A |
| `reports/{report_id}` | A | Frontend |
| `decision_cache/{cache_key}` | A (`system-one`) | A only; Track B never reads or writes it |

`decision_cache` makes System One deterministic (Layer 2): an identical decision request (same seed, tick, persona, options and context; `request_id` excluded) returns the stored decision instead of asking the model again. It changes nothing in the request/response shapes.

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

## 10. Decisions for v1.0

These were the open questions in v0.1. Each is now decided; revisiting one follows section 9.

### 10.1 Zones in `data/zones.geojson` (owner: Track B)

Zones are defined by **kecamatan**, built from OpenStreetMap administrative boundaries, so no one has to hand-draw polygons.

| `zone` / `area_id` | Type | Kecamatan included |
| --- | --- | --- |
| `central` | Parking zone (`parking_tariff` policies) | Gambir, Menteng, Tanah Abang (Jakarta Pusat); Setiabudi (Jakarta Selatan) |
| `jakarta_utara` | Flood area (`flood` events) | Penjaringan, Pademangan, Tanjung Priok, Koja, Cilincing (coastal Jakarta Utara) |

Each GeoJSON feature carries `properties.zone_id` (the value above), `properties.type` (`parking_zone` or `flood_area`), and `properties.kecamatan` (list of names). Adding a new zone is a minor change.

### 10.2 Population size

| Stage | `population_size` |
| --- | --- |
| Layer 1 | 50 |
| Layers 2–5 (development) | 1,000 |
| Layer 6 onward and the demo | 5,000 |

The API accepts 10–20,000 (section 7). Above 15,000, the tick document split in 2.4 must be decided first.

### 10.3 System One model and regions

- **Model:** Gemma 4 `e2b` (smallest) and `e4b`, with Gemma 3 `4b` for comparison, served by Ollama. Track A records the exact model in `model_version` (e.g. `gemma4:e4b`) and the measured agreement with Gemini in `ml/distillation/README.md`.
- **Until Layer 5:** `system-one` runs on CPU in `asia-southeast2`. Layer 0 uses the rule mock (4.4). Layers 1–4 use Gemini as the decider (`decided_by: gemini-system-two`), as the roadmap's Gemini-only MVP requires, and these decisions become the distillation data for Gemma. The rule mock stays as the last-resort fallback (`decided_by: rule-fallback`). Request and response shapes do not change.
- **From Layer 5:** Gemma runs on Cloud Run GPU (one NVIDIA L4) as the private service `gemma` in `asia-southeast1` (Singapore); `system-one` stays on CPU in `asia-southeast2` and calls it when `DECIDER=gemma` (`decided_by: gemma-system-one`), falling back to Gemini and then the rule. The demo keeps `DECIDER=gemini` until a distilled Gemma reaches acceptable agreement. Request and response shapes do not change; the URL is read from config, never hard-coded.
- **Fallback:** if GPU quota or tuning is blocked, `system-one` uses Gemini Flash-Lite with structured output and sets `decided_by` to `gemini-system-two`.
- **Firestore:** the project already has a `(default)` Native database in `asia-southeast2` (created 2022, possibly used by other applications). Shadow City uses its own named database `shadow-city`, Native mode, `asia-southeast2` (section 5).

### 10.4 Decision types in scope for the first demo

- **In scope:** `mode_choice` only.
- **Deferred:** `departure_shift`, `trip_cancel`, `route_choice`. They stay in the enum so adding them later is not a breaking change, but neither track implements them before Layer 7.
- Consequence: in the first demo, `status` values `cancelled` (2.4) and `cancelled_count` (2.5) are always empty or zero.

### 10.5 Backtest reference

- **Backtest `b_0001`:** Jakarta's special Rp1 fare day for Transjakarta, MRT Jakarta, and LRT Jakarta on 24 April 2026. Metric: direction and rough size of the change in transit mode share versus a normal weekday.
- **Reference value:** must come from a published ridership figure for that day. Until one is found, `reference_value` stays `null` and `reference_source` stays `TODO`; the backtest panel shows "reference pending" instead of a number.
- **Plausibility checks (verifier, not backtest):** baseline mode share and population distributions are compared against published aggregate statistics; every reference used is cited in the verifier report's `detail`.
