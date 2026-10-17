"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # "rule" = §4.4 mock only; "gemini" = Gemini decides, rule mock as last-resort fallback.
    decider: str
    project_id: str
    firestore_database: str
    gemini_location: str
    gemini_model: str
    gemini_fallback_model: str
    gemini_concurrency: int


def load_settings() -> Settings:
    return Settings(
        decider=os.environ.get("DECIDER", "rule"),
        project_id=os.environ.get("GCP_PROJECT_ID", "ebc-cloud-dev-03"),
        firestore_database=os.environ.get("FIRESTORE_DATABASE", "shadow-city"),
        gemini_location=os.environ.get("GEMINI_LOCATION", "global"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        gemini_fallback_model=os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
        gemini_concurrency=int(os.environ.get("GEMINI_CONCURRENCY", "16")),
    )
