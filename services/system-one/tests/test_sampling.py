import random

import pytest

from app.models import Mode
from app.sampling import decision_rng, normalize_probabilities, sample

OPTIONS = [Mode.motorcycle, Mode.transjakarta, Mode.krl]


def test_normalize_rescales_to_one():
    probs = normalize_probabilities({"motorcycle": 2, "transjakarta": 1, "krl": 1}, OPTIONS)
    assert probs == {Mode.motorcycle: 0.5, Mode.transjakarta: 0.25, Mode.krl: 0.25}


def test_normalize_drops_invalid_and_unlisted_values():
    raw = {"motorcycle": -1, "transjakarta": "x", "krl": float("nan"), "car": 5, "walk": 1}
    assert normalize_probabilities(raw, OPTIONS) == pytest.approx({o: 1 / 3 for o in OPTIONS})


def test_normalize_missing_options_get_zero():
    probs = normalize_probabilities({"krl": 0.4}, OPTIONS)
    assert probs == {Mode.motorcycle: 0.0, Mode.transjakarta: 0.0, Mode.krl: 1.0}


def test_sample_is_deterministic_for_same_seed_tick_persona():
    probs = {Mode.motorcycle: 0.3, Mode.transjakarta: 0.4, Mode.krl: 0.3}
    picks = {sample(probs, decision_rng(42, 84, "p_00421")) for _ in range(20)}
    assert len(picks) == 1


def test_sample_never_picks_zero_probability_option():
    probs = {Mode.motorcycle: 0.0, Mode.transjakarta: 1.0, Mode.krl: 0.0}
    for tick in range(200):
        assert sample(probs, decision_rng(42, tick, "p_1")) is Mode.transjakarta


def test_sample_follows_probabilities_roughly():
    probs = {Mode.motorcycle: 0.2, Mode.transjakarta: 0.8}
    rng = random.Random(0)
    picks = [sample(probs, rng) for _ in range(5000)]
    assert picks.count(Mode.transjakarta) / 5000 == pytest.approx(0.8, abs=0.03)
