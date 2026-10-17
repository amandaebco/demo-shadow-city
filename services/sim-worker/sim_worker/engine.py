"""Deterministic placeholder tick loop for Layer 0 (Foundation).

In Layer 0, this module provides the deterministic tick loop skeleton (ticks 0000-0203)
seeded by the scenario's integer seed, without performing real routing or calling
external services yet.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any

from sim_worker.config import (
    BASE_HOUR,
    MINUTES_PER_TICK,
    START_TICK,
    TOTAL_TICKS,
)


def format_tick_id(tick: int) -> str:
    """Format a tick number as a 4-digit zero-padded string per CONTRACT.md section 5."""
    if tick < 0 or tick >= TOTAL_TICKS:
        raise ValueError(f"tick must be between {START_TICK} and {TOTAL_TICKS - 1}, got {tick}")
    return f"{tick:04d}"


def tick_to_local_time(tick: int) -> str:
    """Convert a tick index (0 = 05:00) into HH:MM local time string."""
    total_minutes = BASE_HOUR * 60 + tick * MINUTES_PER_TICK
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def make_tick_rng(seed: int, tick: int, salt: str = "") -> random.Random:
    """Create a deterministic RNG derived from scenario seed, tick, and optional salt."""
    payload = f"{seed}:{tick}:{salt}".encode("utf-8")
    derived_seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return random.Random(derived_seed)


@dataclass(frozen=True)
class TickState:
    """Per-tick state document shape matching CONTRACT.md section 2.4."""

    scenario_id: str
    tick: int
    tick_id: str
    simulated_time: str
    persona_ids: list[str]
    lat: list[float]
    lng: list[float]
    mode: list[str]
    status: list[str]

    def to_firestore_dict(self) -> dict[str, Any]:
        """Serialize to the exact Firestore schema defined in CONTRACT.md section 2.4."""
        return {
            "scenario_id": self.scenario_id,
            "tick": self.tick,
            "persona_ids": self.persona_ids,
            "lat": self.lat,
            "lng": self.lng,
            "mode": self.mode,
            "status": self.status,
        }


def run_placeholder_tick_loop(
    scenario_id: str,
    seed: int,
    total_ticks: int = TOTAL_TICKS,
) -> list[TickState]:
    """Run the Layer 0 deterministic placeholder tick loop from tick 0 to total_ticks - 1.

    TODO(Layer 1+): Replace empty agent arrays with real persona simulation,
    System One batch calls, and Firestore / BigQuery writes.
    """
    if total_ticks <= 0 or total_ticks > TOTAL_TICKS:
        raise ValueError(f"total_ticks must be in 1..{TOTAL_TICKS}, got {total_ticks}")

    states: list[TickState] = []
    for tick in range(START_TICK, total_ticks):
        # Deterministic RNG initialized per tick so future layers remain reproducible
        _rng = make_tick_rng(seed=seed, tick=tick)
        states.append(
            TickState(
                scenario_id=scenario_id,
                tick=tick,
                tick_id=format_tick_id(tick),
                simulated_time=tick_to_local_time(tick),
                persona_ids=[],
                lat=[],
                lng=[],
                mode=[],
                status=[],
            )
        )
    return states

