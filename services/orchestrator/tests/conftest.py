import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app


class FakeStore:
    def __init__(self):
        self.scenarios, self.personas, self.metrics, self.reports = {}, {}, {}, {}

    def create_scenario(self, scenario):
        assert scenario["scenario_id"] not in self.scenarios
        self.scenarios[scenario["scenario_id"]] = dict(scenario)

    def get_scenario(self, scenario_id):
        return self.scenarios.get(scenario_id)

    def list_scenarios(self, limit=100):
        return sorted(self.scenarios.values(), key=lambda s: s["created_at"], reverse=True)[:limit]

    def update_scenario(self, scenario_id, fields):
        self.scenarios[scenario_id].update(fields)

    def get_metrics(self, scenario_id):
        return self.metrics.get(scenario_id)

    def get_report(self, report_id):
        return self.reports.get(report_id)

    def save_report(self, report):
        self.reports[report["report_id"]] = report

    def get_persona(self, persona_id):
        return self.personas.get(persona_id)

    def count_personas(self, population_id):
        return sum(1 for p in self.personas.values() if p["population_id"] == population_id)

    def write_personas(self, personas):
        for p in personas:
            self.personas[p["persona_id"]] = p


class FakePublisher:
    def __init__(self):
        self.started, self.failed = [], []

    def scenario_start(self, scenario_id, seed):
        self.started.append({"scenario_id": scenario_id, "seed": seed})

    def scenario_failed(self, scenario_id, stage, error):
        self.failed.append({"scenario_id": scenario_id, "stage": stage, "error": error})


def fake_profile(index):
    return {
        "index": index,
        "occupation": "office worker",
        "vehicles": ["motorcycle"],
        "usual_mode": "motorcycle",
        "usual_departure_tick": 24,
        "cost_sensitivity": 0.7,
        "time_sensitivity": 0.6,
        "profile_summary": "Office worker who rides a motorcycle.",
    }


class FakeReportWriter:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def write(self, scenario, metrics, base_scenario=None, base_metrics=None):
        self.calls += 1
        self.last_base = base_scenario
        if self.fail:
            raise RuntimeError("Vertex AI unavailable")
        from app.report import report_id_for

        return {"report_id": report_id_for(scenario["scenario_id"]), "scenario_id": scenario["scenario_id"],
                "headline": "Summary.", "generated_by": "gemini-system-two"}


class FakeGeminiModels:
    """Answers every persona prompt with a valid profile for each listed index."""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def generate_content(self, model, contents, config):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Vertex AI unavailable")
        indices = [json.loads(line)["index"] for line in contents.splitlines()[1:]]
        return SimpleNamespace(text=json.dumps([fake_profile(i) for i in indices]))


def fake_client(models):
    return SimpleNamespace(aio=SimpleNamespace(models=models))


@pytest.fixture
def deps():
    from app.population import PersonaGenerator

    models = FakeGeminiModels()
    return SimpleNamespace(
        store=FakeStore(),
        publisher=FakePublisher(),
        models=models,
        generator=PersonaGenerator(fake_client(models), "fake-model"),
        report_writer=FakeReportWriter(),
    )


@pytest.fixture
def client(deps):
    names = ("store", "generator", "publisher", "report_writer")
    for name in names:
        setattr(app.state, name, getattr(deps, name))
    with TestClient(app) as test_client:
        yield test_client
    for name in names:
        delattr(app.state, name)
