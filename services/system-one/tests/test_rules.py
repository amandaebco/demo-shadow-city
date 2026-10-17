import pytest

from app.models import DecidedBy, DecisionRequestItem, Mode
from app.rules import MODEL_VERSION, decide, decision_id_for, normalize, score_options


def make(item: dict, **context_overrides) -> DecisionRequestItem:
    item["context"].update(context_overrides)
    return DecisionRequestItem.model_validate(item)


def set_options(item: dict, details: dict) -> None:
    item["options"] = list(details)
    item["context"]["options_detail"] = details


def test_normalize_min_max():
    assert normalize([10, 20, 30]) == [0.0, 0.5, 1.0]


def test_normalize_all_equal_is_zero():
    assert normalize([5, 5, 5]) == [0.0, 0.0, 0.0]


def test_contract_example_picks_transjakarta(item):
    result = decide(make(item))
    assert result.chosen is Mode.transjakarta


def test_score_matches_hand_computation(item):
    scores = score_options(make(item))
    # motorcycle: 0.6 * (72-58)/(75-58) + 0.7 * (30000-3500)/(45000-3500)
    assert scores[Mode.motorcycle] == pytest.approx(0.6 * 14 / 17 + 0.7 * 26500 / 41500)
    assert scores[Mode.transjakarta] == pytest.approx(0.0)
    assert scores[Mode.ojol] == pytest.approx(1.3)


def test_time_sensitive_persona_picks_fastest(item):
    set_options(item, {
        "car": {"est_minutes": 30, "cost_idr": 50000},
        "krl": {"est_minutes": 60, "cost_idr": 5000},
    })
    assert decide(make(item, time_sensitivity=1.0, cost_sensitivity=0.0)).chosen is Mode.car


def test_cost_sensitive_persona_picks_cheapest(item):
    set_options(item, {
        "car": {"est_minutes": 30, "cost_idr": 50000},
        "krl": {"est_minutes": 60, "cost_idr": 5000},
    })
    assert decide(make(item, time_sensitivity=0.0, cost_sensitivity=1.0)).chosen is Mode.krl


def test_tie_goes_to_first_listed_option(item):
    set_options(item, {
        "krl": {"est_minutes": 40, "cost_idr": 5000},
        "mrt": {"est_minutes": 40, "cost_idr": 5000},
    })
    assert decide(make(item)).chosen is Mode.krl
    item["options"] = ["mrt", "krl"]
    assert decide(make(item)).chosen is Mode.mrt


def test_single_option_is_chosen(item):
    set_options(item, {"walk": {"est_minutes": 20, "cost_idr": 0}})
    result = decide(make(item))
    assert result.chosen is Mode.walk
    assert result.probabilities == {Mode.walk: 1.0}


def test_options_detail_entries_not_in_options_are_ignored(item):
    item["options"] = ["motorcycle", "ojol"]
    result = decide(make(item))
    assert set(result.probabilities) == {Mode.motorcycle, Mode.ojol}
    assert result.chosen is Mode.motorcycle


def test_probabilities_are_one_hot_and_sum_to_one(item):
    result = decide(make(item))
    assert set(result.probabilities) == set(make(item).options)
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.probabilities[result.chosen] == 1.0


def test_response_fields(item):
    result = decide(make(item))
    assert result.request_id == "q_000981"
    assert result.decided_by is DecidedBy.rule_fallback
    assert result.model_version == MODEL_VERSION
    assert result.decision_id.startswith("d_")
    assert 0 < len(result.reason_short) <= 140
    assert result.latency_ms >= 0


def test_decision_is_deterministic(item):
    first = decide(make(item)).model_dump(exclude={"latency_ms"})
    second = decide(make(item)).model_dump(exclude={"latency_ms"})
    assert first == second
    assert decision_id_for("q_1") != decision_id_for("q_2")
