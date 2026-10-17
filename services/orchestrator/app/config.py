"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    project_id: str
    firestore_database: str
    gemini_location: str
    gemini_model: str
    topic_scenario_start: str
    topic_scenario_failed: str


def load_settings() -> Settings:
    return Settings(
        project_id=os.environ.get("GCP_PROJECT_ID", "ebc-cloud-dev-03"),
        firestore_database=os.environ.get("FIRESTORE_DATABASE", "shadow-city"),
        gemini_location=os.environ.get("GEMINI_LOCATION", "global"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        topic_scenario_start=os.environ.get("TOPIC_SCENARIO_START", "scenario-start"),
        topic_scenario_failed=os.environ.get("TOPIC_SCENARIO_FAILED", "scenario-failed"),
    )
