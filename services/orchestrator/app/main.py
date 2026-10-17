"""Orchestrator service (CONTRACT.md §3). Layer 0: health endpoint only."""

import os

from fastapi import FastAPI

SERVICE_VERSION = "0.1.0"

app = FastAPI(title="Shadow City Orchestrator", version=SERVICE_VERSION)


@app.get("/v1/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "orchestrator",
        "version": SERVICE_VERSION,
        "project": os.environ.get("GCP_PROJECT_ID"),
    }
