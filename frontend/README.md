# `frontend` — Shadow City Map Web App (Track B)

**Current Layer:** Layer 3, Layer 4, Layer 6 Scale Showcase, Layer 7 Backtest & Demo UX Polish — Policy & flood comparison view, Verifier Agent report tab, 5,000-resident clustered scale showcase, Rp1 fare day backtest panel (`GET /v1/backtests/b_0001`), resident-weighted kecamatan breakdown, per-resident decision evidence chain (`Shared from <persona_id>`), and 1080p demo UX polish (`docs/REFERENCE.md` §9–10, `docs/CONTRACT.md` v1.8).

This Next.js + React static web application (deployed on Firebase Hosting site `shadow-city` at `https://shadow-city.web.app`) renders the Jakarta policy simulator map, animates 1,000 to 5,000 resident dots moving along the OSM road network across ticks `0000`–`0203` (`05:00`–`21:55` WIB) via a single WebGL GeoJSON source, presents a side-by-side **Comparison vs. Baseline** view (`GET /v1/scenarios/{id}/compare` + `GET /v1/scenarios/{id}/report`), displays the **Verifier Report** (`GET /v1/scenarios/{id}/verification`) and **Backtest** (`GET /v1/backtests/b_0001`), and lets users find or click any resident dot to inspect their full **Decision Evidence Chain** (`scenarios/{id}/decisions/{persona_id}` + `GET /v1/personas/{persona_id}`).

## Features in Layer 3, Layer 4, Layer 6, Layer 7 & Demo UX Polish

- **Layer 7 Lite — Rp1 Fare Day Backtest (`GET /v1/backtests/b_0001`, `CONTRACT.md` v1.8 §8):**
  - Displays the direction-only backtest for Jakarta's Rp1 fare day (`24 April 2026`, scenario `s_rp1_fare_day_24_april_2026_0acbd5` vs. `s_baseline_weekday_ea7247`): description, simulated change in transit mode share (`+10.3 pp`, direction: `increase`), reported direction (`increase`) with clickable ANTARA source link, explicit text status (`Direction match: Yes`), `Magnitude: reference pending (no official daily ridership published)`, and scope notes.
- **Layer 6 Scale Showcase (`Scale: 5,000 residents (clustered)`):**
  - Includes `s_layer_6_clustered_baseline_run_a_n_5000__0388aa` in the Scenario Picker right below the three 1,000-resident demo scenarios.
  - Smoothly renders and animates all 5,000 residents at 1080p using a pre-allocated in-place WebGL GeoJSON `FeatureCollection` buffer (zero DOM markers).
  - Displays the **Scale & cost** card with measured values: `5,000 residents · 377 clusters · 377 model calls instead of 5,000 (−92.5%) · ~2 minutes end to end · $0.72 in Gemini calls · replay from cache: $0`.
  - Clicking any resident in the 5,000-resident scenario displays `Shared from <persona_id>` in the Decision Evidence Chain panel (`CONTRACT.md` v1.7 §4.6).
- **Streamlined Video Flow & Scenario Picker:**
  - Groups the primary 1,000-resident demo scenarios (`Baseline weekday`, `Central parking +100%`, `Central parking +100% with North Jakarta tidal flood`) at the top of the Scenario Picker, parallelizes API + Firestore fetches, and caches completed scenario bundles in memory for instant switching during live demos.
- **Comparison vs. Baseline View (`GET /v1/scenarios/{id}/compare`):**
  - Displays side-by-side citywide metrics (`Avg travel time`, `Avg commute cost`, `Residents stuck in flood`) with explicit `Δ vs baseline` badges comparing the active scenario against its `base_scenario_id` (or any user-selected baseline via `?base=`).
  - Renders stacked **Baseline** vs. **Scenario** mode-share bars and a mode-by-mode percentage-point shift table (`Δ +X.X pp` / `Δ -X.X pp`).
  - Includes a tabbed **Income & Kecamatan** breakdown (`src/lib/kelurahanMap.ts`) showing plain-English income groups and **resident-weighted kecamatan** travel time, IDR cost, and flood-stuck deltas alongside the **Analyst Report** (`headline`, `winners`, `losers`, `recommendations`, `caveats`).
- **Layer 4 Verifier Report Tab (`GET /v1/scenarios/{id}/verification`):**
  - Displays the Verifier Agent's overall result (`Overall status: PASS` / `WARN` / `FAIL`, with check pass/warning/fail counts) and each check's plain-English title, explicit text status (`Status: PASS` / `Status: WARN` / `Status: FAIL`), and detailed audit explanation.
- **Find Resident & Decision Evidence Chain (`CONTRACT.md` v1.5 §4.5):**
  - Includes a **Find Resident (Decision Evidence)** search box by persona ID or 5-digit index and quick-pick buttons that highlight the resident on the map on hover and fly to their position on click.
  - Clicking any resident opens the **Resident Commute Decision · Evidence Chain** panel showing `profile_summary`, `usual_mode`, `Baseline mode`, `Today's chosen mode`, `reason_short`, and the full table of evaluated options (`Travel time`, `Flooded route` / `Clear route` text badge, `Cost`, and `Probability`).
- **1080p Map Legibility & Clear Loading/Empty States:**
  - High-contrast on-map labels and outlines for the **Central Parking Zone (+100% tariff)** and **North Jakarta Tidal Flood Area**, readable 1080p legend, plain-English text statuses throughout (never color-only), and explicit loading and empty states on every panel.
- **Animated Resident Commutes:** Animates 1,000 synthetic Jakarta residents across ticks `0000`–`0203` colored by chosen transport mode (`car`, `motorcycle`, `transjakarta`, `krl`, `mrt`, `ojol`, `walk`) with interactive hover tooltips (`persona_id`, `mode`, `status`).
- **Firestore `shadow-city` Integration (`src/lib/firestore.ts`, `firestore.rules`):** Uses `getFirestore(app, "shadow-city")` in project `ebc-cloud-dev-03` (`CONTRACT.md` §5), accompanied by read-only client security rules (`firestore.rules`) for `scenarios/**` on database `shadow-city`.
- **Timeline Playback Controls:** Play/Pause, `1x` / `2x` / `4x` speed selector, tick scrubber (`0000`–`0203`), simulated Jakarta clock (`05:00`–`21:55` WIB), and live status counters (`At Home`, `Traveling`, `Flood Delayed`, `At Work`).
- **Scenario Picker & Creator:** Connects to Track A's Orchestrator (`/v1/**` rewrite on Firebase Hosting) to select existing scenarios or create new 1,000-persona policy/flood comparison scenarios (`POST /v1/scenarios`).
- **Policy & Flood Zone Overlay:** Toggleable OpenStreetMap administrative boundaries (`central` parking zone and `jakarta_utara` flood area) from `data/zones.geojson`.

## How to Run Locally

From `frontend/`:

```bash
# 1. Install dependencies
npm install

# 2. Start local development server (http://localhost:3000)
npm run dev
```

## How to Build & Deploy to Firebase (`ebc-cloud-dev-03`)

> **Note:** Confirm with a human before deploying Firestore rules or Hosting to `ebc-cloud-dev-03`. `firebase.json` scopes Firestore rules strictly to the named database `shadow-city` (never `(default)`).

From `frontend/`:

```bash
npm run build
firebase deploy --only firestore:rules,hosting --project ebc-cloud-dev-03
```
