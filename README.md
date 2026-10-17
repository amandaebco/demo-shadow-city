# Shadow City

> Ringkasan proyek — TODO.

## Struktur Repo

```
shadow-city/
├── AGENTS.md              # instruksi tetap untuk coding agent
├── docs/
│   ├── REFERENCE.md       # Shadow City — Development Reference
│   └── CONTRACT.md        # kontrak antar-service
├── services/
│   ├── orchestrator/      # Track A — FastAPI + ADK, Gemini agents
│   ├── system-one/        # Track A — endpoint /v1/decide (mock → Gemma)
│   └── sim-worker/        # Track B — mesin simulasi deterministik
├── frontend/              # Track B — web app peta (Firebase Hosting)
├── data/
│   └── zones.geojson      # Track B — zona parkir dan area banjir
├── ml/
│   └── distillation/      # Track A — data teacher + skrip tuning Gemma
└── infra/                 # skrip deploy Cloud Run, Pub/Sub, BigQuery
```

## Cara Menjalankan

TODO
