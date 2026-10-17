# `frontend` — Shadow City Map Web App (Track B)

**Current Layer:** Layer 1 — Gemini-only MVP (`docs/REFERENCE.md` §9, `docs/CONTRACT.md` v1.2).

This Next.js + React static web application renders the Jakarta policy simulator map, animates resident dots moving across ticks `0000`–`0203` (`05:00`–`21:55` WIB), and displays the Gemini Analyst Report (`GET /v1/scenarios/{id}/report`) and citywide metrics (`GET /v1/scenarios/{id}/metrics`).

## Features in Layer 1

- **Animated Resident Commutes:** Animates 50 synthetic Jakarta residents across ticks `0000`–`0203` colored by chosen transport mode (`car`, `motorcycle`, `transjakarta`, `krl`, `mrt`, `ojol`, `walk`) with interactive hover tooltips (`persona_id`, `mode`, `status`).
- **Firestore `shadow-city` Integration (`src/lib/firestore.ts`, `firestore.rules`):** Uses `getFirestore(app, "shadow-city")` in project `ebc-cloud-dev-03` (`CONTRACT.md` §5), accompanied by read-only client security rules (`firestore.rules`) for `scenarios/**` on database `shadow-city`.
- **Timeline Playback Controls:** Play/Pause, `1x` / `2x` / `4x` speed selector, tick scrubber (`0000`–`0203`), simulated Jakarta clock (`05:00`–`21:55` WIB), and live status counters (`At Home`, `Traveling`, `Flood Delayed`, `At Work`).
- **Scenario Picker & Creator:** Connects to Track A's Orchestrator (`NEXT_PUBLIC_ORCHESTRATOR_URL`) to select existing scenarios (defaulting to `s_layer_1_smoke_test_803984`) or create new 50-persona policy/flood scenarios (`POST /v1/scenarios`).
- **Result Summary Drawer:** Displays Track A's Gemini analyst report (`headline`, `winners`, `losers`, `recommendations`, `caveats`) from `GET /v1/scenarios/{id}/report` along with citywide mode share and average travel time/cost.
- **Policy & Flood Zone Overlay:** Toggleable OpenStreetMap administrative boundaries (`central` parking zone and `jakarta_utara` flood area) from `data/zones.geojson`.

## How to Run Locally

From `frontend/`:

```bash
# 1. Install dependencies
npm install

# 2. Optional: fetch Firebase web config (once a web app is registered in ebc-cloud-dev-03)
firebase apps:sdkconfig web --project ebc-cloud-dev-03

# 3. Start local development server (http://localhost:3000)
npm run dev
```

## How to Build & Deploy to Firebase (`ebc-cloud-dev-03`)

> **Note:** Confirm with a human before deploying Firestore rules or Hosting to `ebc-cloud-dev-03`. `firebase.json` scopes Firestore rules strictly to the named database `shadow-city` (never `(default)`).

From `frontend/`:

```bash
npm run build
firebase deploy --only firestore:rules,hosting --project ebc-cloud-dev-03
```
