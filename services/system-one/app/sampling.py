"""Deterministic sampling of the chosen option (CONTRACT.md §2.3)."""

import hashlib
import math
import random

from app.models import Mode


def persona_hash(persona_id: str) -> int:
    # Stable across processes, unlike Python's built-in hash().
    return int(hashlib.sha256(persona_id.encode("utf-8")).hexdigest()[:8], 16)


def scenario_seed_fallback(scenario_id: str) -> int:
    """Used only when the scenario's seed cannot be looked up."""
    return int(hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:8], 16)


def decision_rng(seed: int, tick: int, persona_id: str) -> random.Random:
    """RNG seeded with seed + tick + persona_id hash, as the contract specifies."""
    return random.Random(seed + tick + persona_hash(persona_id))


def normalize_probabilities(raw: dict, options: list[Mode]) -> dict[Mode, float]:
    """Keep only listed options, drop invalid values, and rescale to sum to 1."""
    cleaned = {}
    for option in options:
        value = raw.get(option.value, 0.0)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0
        cleaned[option] = value if math.isfinite(value) and value > 0 else 0.0
    total = sum(cleaned.values())
    if total == 0:
        return {option: 1.0 / len(options) for option in options}
    return {option: value / total for option, value in cleaned.items()}


def sample(probabilities: dict[Mode, float], rng: random.Random) -> Mode:
    """Inverse-CDF sample over options in their listed order."""
    r = rng.random()
    cumulative = 0.0
    last = None
    for option, p in probabilities.items():
        cumulative += p
        last = option
        if r < cumulative:
            return option
    return last  # Guards against floating-point rounding at the top end.
