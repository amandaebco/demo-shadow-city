import asyncio
import json
from types import SimpleNamespace

import pytest

from app.report import NO_BASELINE_CAVEAT, STANDARD_CAVEAT, ReportWriter, build_prompt, report_id_for

SCENARIO = {
    "scenario_id": "s_parking_up_abc123",
    "name": "Central parking +100%",
    "base_scenario_id": None,
    "population_size": 50,
    "policies": [{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
    "events": [],
}
METRICS = {"scenario_id": "s_parking_up_abc123", "citywide": {"avg_travel_min": 58.9}}


class FakeModels:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    async def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        return SimpleNamespace(text=self.text)


def writer(reply: dict | str):
    models = FakeModels(reply if isinstance(reply, str) else json.dumps(reply))
    return ReportWriter(SimpleNamespace(aio=SimpleNamespace(models=models)), "fake-model"), models


def test_report_id():
    assert report_id_for("s_parking_up_abc123") == "r_analyst_parking_up_abc123"


def test_prompt_contains_scenario_and_metrics():
    prompt = build_prompt(SCENARIO, METRICS)
    assert "parking_tariff" in prompt and "58.9" in prompt


def test_report_shape_and_cleanup():
    w, _ = writer({
        "headline": " Commuters shift to transit. ",
        "winners": ["a", "", "b", "c", "d", "e"],
        "losers": "not a list",
        "recommendations": ["r"],
        "caveats": [],
    })
    report = asyncio.run(w.write(SCENARIO, METRICS))
    assert report["report_id"] == "r_analyst_parking_up_abc123"
    assert report["headline"] == "Commuters shift to transit."
    assert report["winners"] == ["a", "b", "c", "d"]
    assert report["losers"] == []
    assert report["caveats"] == [STANDARD_CAVEAT, NO_BASELINE_CAVEAT]
    assert report["generated_by"] == "gemini-system-two"
    assert report["base_scenario_id"] is None


def test_missing_headline_raises():
    w, _ = writer({"headline": "", "winners": [], "losers": [], "recommendations": [], "caveats": []})
    with pytest.raises(ValueError):
        asyncio.run(w.write(SCENARIO, METRICS))


def test_prompt_forbids_causal_claims_without_baseline():
    assert "no baseline scenario" in build_prompt(SCENARIO, METRICS)
    with_base = SCENARIO | {"base_scenario_id": "s_baseline_weekday"}
    assert "no baseline scenario" not in build_prompt(with_base, METRICS)


def test_no_baseline_caveat_only_without_baseline():
    reply = {"headline": "h", "winners": [], "losers": [], "recommendations": [], "caveats": []}
    w, _ = writer(reply)
    report = asyncio.run(w.write(SCENARIO | {"base_scenario_id": "s_base"}, METRICS))
    assert NO_BASELINE_CAVEAT not in report["caveats"]
