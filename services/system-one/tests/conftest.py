import copy

import pytest
from fastapi.testclient import TestClient

from app.main import app

# The request item example from CONTRACT.md §2.3.
CONTRACT_EXAMPLE_ITEM = {
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
            "motorcycle": {"est_minutes": 72, "cost_idr": 30000, "flooded_on_route": True},
            "transjakarta": {"est_minutes": 58, "cost_idr": 3500, "flooded_on_route": False},
            "krl": {"est_minutes": 65, "cost_idr": 5000, "flooded_on_route": False},
            "ojol": {"est_minutes": 75, "cost_idr": 45000, "flooded_on_route": True},
        },
        "active_policies": ["parking_tariff:central:+100%"],
        "active_events": ["flood:jakarta_utara"],
    },
}


@pytest.fixture
def item() -> dict:
    return copy.deepcopy(CONTRACT_EXAMPLE_ITEM)


class RecordingDecisionLog:
    def __init__(self):
        self.rows = []

    def write(self, rows):
        self.rows.extend(rows)


@pytest.fixture
def decision_log():
    return RecordingDecisionLog()


@pytest.fixture
def client(decision_log):
    app.state.decision_log = decision_log
    with TestClient(app) as test_client:
        yield test_client
    del app.state.decision_log
