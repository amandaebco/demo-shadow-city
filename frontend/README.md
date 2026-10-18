# `frontend` — Shadow City Map Web App (Track B)

**Current Layer:** Layer 3 & Demo Polish — Policy & flood comparison view, resident-weighted kecamatan breakdown, and per-resident decision evidence chain (`docs/REFERENCE.md` §9, `docs/CONTRACT.md` v1.5).

This Next.js + React static web application (deployed on Firebase Hosting site `shadow-city` at `https://shadow-city.web.app`) renders the Jakarta policy simulator map, animates up to 1,000 resident dots moving along the OSM road network across ticks `0000`–`0203` (`05:00`–`21:55` WIB), presents a side-by-side **Baseline vs. Variant Comparison View** (`GET /v1/scenarios/{id}/compare` + `GET /v1/scenarios/{id}/report`), and lets users click any resident dot to inspect their full **Decision Evidence Chain** (`scenarios/{id}/decisions/{persona_id}` + `GET /v1/personas/{persona_id}`).

## Features in Layer 3 & Demo Polish

- **Baseline vs. Variant Comparison View (`GET /v1/scenarios/{id}/compare`):**
  - Displays side-by-side citywide numbers (`Avg Travel Time`, `Avg Commute Cost`, `Flood-Delayed`) with signed delta badges comparing the active variant against its `base_scenario_id` (or any user-selected baseline via `?base=`).
  - Renders stacked **Baseline** vs. **Variant** mode-share bars and a mode-by-mode percentage-point shift table (`+X.X pp` / `-X.X pp`).
  - Includes a tabbed **By Income & Kecamatan** breakdown (`src/lib/kelurahanMap.ts`) showing per-income-band and **resident-weighted kecamatan** travel time and IDR cost deltas (with a `Residents` column, aggregating kelurahan with `< 10` residents into their kecamatan) alongside the **Analyst Report** (`headline`, `winners`, `losers`, `recommendations`, `caveats`).
- **Click a Resident → Decision Evidence Chain (`CONTRACT.md` v1.5 §4.5):**
  - Clicking any resident dot on the map (or picking one of the featured mode-switching commuters in the legend) opens the **Resident Decision · Evidence Chain** panel showing `profile_summary`, `usual_mode`, today's `chosen` mode (and baseline mode when comparing), `reason_short`, and the full table of evaluated options (`est_minutes`, `cost_idr`, `flooded_on_route`, and `probabilities`).
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
