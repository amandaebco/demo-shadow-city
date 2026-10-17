"""Configuration and contract constants for Shadow City sim-worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

EXPECTED_GCP_PROJECT_ID = "ebc-cloud-dev-03"
EXPECTED_FIRESTORE_DATABASE = "shadow-city"

DEFAULT_SYSTEM_ONE_URL = "https://system-one-697653429683.asia-southeast2.run.app"
DEFAULT_ORCHESTRATOR_URL = "https://orchestrator-697653429683.asia-southeast2.run.app"
DEFAULT_PUBSUB_SUBSCRIPTION = "scenario-start-sim-worker"

# Simulation time constants (docs/CONTRACT.md section 1)
START_TICK: int = 0
END_TICK: int = 203
TOTAL_TICKS: int = 204  # Ticks 0..203 inclusive (05:00 to 22:00 local time)
MINUTES_PER_TICK: int = 5
BASE_HOUR: int = 5  # Tick 0 = 05:00 local time


@dataclass(frozen=True)
class WorkerConfig:
    """Runtime configuration read from environment variables."""

    gcp_project_id: str
    gcp_region: str
    firestore_database: str
    bigquery_dataset: str
    system_one_url: str
    orchestrator_url: str
    pubsub_subscription: str
    zones_geojson_path: Path
    network_json_path: Path

    @classmethod
    def from_env(cls) -> WorkerConfig:
        project_id = os.getenv("GCP_PROJECT_ID", EXPECTED_GCP_PROJECT_ID)
        if project_id != EXPECTED_GCP_PROJECT_ID:
            raise ValueError(
                f"Invalid GCP_PROJECT_ID={project_id!r}. "
                f"Shadow City resources must only use {EXPECTED_GCP_PROJECT_ID!r}."
            )

        firestore_db = os.getenv("FIRESTORE_DATABASE", EXPECTED_FIRESTORE_DATABASE)
        if firestore_db != EXPECTED_FIRESTORE_DATABASE:
            raise ValueError(
                f"Invalid FIRESTORE_DATABASE={firestore_db!r}. "
                f"Shadow City must only use the named database {EXPECTED_FIRESTORE_DATABASE!r}."
            )

        default_zones = Path(__file__).resolve().parents[3] / "data" / "zones.geojson"
        zones_path = Path(os.getenv("ZONES_GEOJSON_PATH", str(default_zones)))

        default_network = Path(__file__).resolve().parent / "data" / "jakarta_network.json"
        network_path = Path(os.getenv("NETWORK_JSON_PATH", str(default_network)))

        return cls(
            gcp_project_id=project_id,
            gcp_region=os.getenv("GCP_REGION", "asia-southeast2"),
            firestore_database=firestore_db,
            bigquery_dataset=os.getenv("BIGQUERY_DATASET", "shadow_city"),
            system_one_url=os.getenv("SYSTEM_ONE_URL", DEFAULT_SYSTEM_ONE_URL).rstrip("/"),
            orchestrator_url=os.getenv("ORCHESTRATOR_URL", DEFAULT_ORCHESTRATOR_URL).rstrip("/"),
            pubsub_subscription=os.getenv("PUBSUB_SUBSCRIPTION", DEFAULT_PUBSUB_SUBSCRIPTION),
            zones_geojson_path=zones_path,
            network_json_path=network_path,
        )
