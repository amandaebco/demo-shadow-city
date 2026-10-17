# `frontend` — Shadow City Map Web App (Track B)

**Current Layer:** Layer 0 — Foundation (`docs/REFERENCE.md` §9).

This Next.js + React static web application renders an interactive map of Jakarta (`-6.1754, 106.8272`) and is configured for deployment to **Firebase Hosting** in GCP project `ebc-cloud-dev-03`.

## Features in Layer 0

- Full-screen interactive map of Jakarta (`src/components/JakartaMap.tsx`) using MapLibre GL + CARTO Dark Matter basemap tiles (no API key required to render Layer 0).
- Optional toggle to preview the OpenStreetMap administrative boundary zones from `data/zones.geojson` (`central` parking zone and `jakarta_utara` flood area per `docs/CONTRACT.md` §10.1).
- Explicit configuration for `GCP_PROJECT_ID=ebc-cloud-dev-03` and `FIRESTORE_DATABASE=shadow-city` (`src/lib/config.ts`, `.env.example`, `.firebaserc`).
- Static export (`output: "export"`, `distDir: "dist"`) ready for Firebase Hosting (`firebase.json`).

## How to Run Locally

From `frontend/`:

```bash
# 1. Install dependencies
npm install

# 2. Optional: copy .env.example to .env
cp .env.example .env

# 3. Start local development server (http://localhost:3000)
npm run dev
```

## How to Build Static Bundle

From `frontend/`:

```bash
npm run build
```

This generates the static bundle in `frontend/dist/`.

## How to Deploy to Firebase Hosting (`ebc-cloud-dev-03`)

> **Note:** Always pass `--project ebc-cloud-dev-03` explicitly and confirm before deploying.

From `frontend/`:

```bash
npm run build
firebase deploy --only hosting --project ebc-cloud-dev-03
```
