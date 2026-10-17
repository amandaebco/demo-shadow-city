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
    report = asyncio.run(w.write(SCENARIO | {"base_scenario_id": "s_base"}, METRICS,
                                 SCENARIO | {"scenario_id": "s_base"}, METRICS))
    assert NO_BASELINE_CAVEAT not in report["caveats"]


BASE_SCENARIO = SCENARIO | {"scenario_id": "s_base", "name": "Baseline", "policies": [], "seed": 42,
                            "population_size": 50, "population_id": "pop_s42_n50"}
VARIANT_SCENARIO = SCENARIO | {"base_scenario_id": "s_base", "seed": 42, "population_id": "pop_s42_n50"}
BASE_METRICS = {"citywide": {"avg_travel_min": 40.0, "mode_share": {"car": 0.10}}, "by_kelurahan": []}
VARIANT_METRICS = {"citywide": {"avg_travel_min": 43.5, "mode_share": {"car": 0.04}}, "by_kelurahan": []}


def test_comparison_prompt_has_code_computed_deltas_and_allows_attribution():
    from app.report import build_comparison_prompt

    prompt = build_comparison_prompt(VARIANT_SCENARIO, VARIANT_METRICS, BASE_SCENARIO, BASE_METRICS)
    assert '"avg_travel_min": 3.5' in prompt and '"car": -6.0' in prompt
    assert '"policies_added"' in prompt and "parking_tariff" in prompt
    assert "come from the policy and event changes" in prompt
    assert "no baseline scenario" not in prompt


def test_comparison_with_different_population_is_flagged():
    from app.report import NOT_COMPARABLE_CAVEAT, build_comparison_prompt

    other = BASE_SCENARIO | {"seed": 7}
    assert "NOT a clean counterfactual" in build_comparison_prompt(VARIANT_SCENARIO, VARIANT_METRICS, other, BASE_METRICS)
    w, _ = writer({"headline": "h", "winners": [], "losers": [], "recommendations": [], "caveats": []})
    report = asyncio.run(w.write(VARIANT_SCENARIO, VARIANT_METRICS, other, BASE_METRICS))
    assert NOT_COMPARABLE_CAVEAT in report["caveats"]
    assert NO_BASELINE_CAVEAT not in report["caveats"]


def test_comparable_baseline_has_no_extra_caveat():
    from app.report import NOT_COMPARABLE_CAVEAT

    w, models = writer({"headline": "h", "winners": [], "losers": [], "recommendations": [], "caveats": []})
    report = asyncio.run(w.write(VARIANT_SCENARIO, VARIANT_METRICS, BASE_SCENARIO, BASE_METRICS))
    assert NOT_COMPARABLE_CAVEAT not in report["caveats"] and NO_BASELINE_CAVEAT not in report["caveats"]
    assert "Baseline scenario" in models.prompts[0]
