"""Result of deciding one request item, as passed from a decider to the endpoint."""

from dataclasses import dataclass

from app.costs import Usage
from app.models import DecisionResponseItem


@dataclass(frozen=True)
class Outcome:
    response: DecisionResponseItem
    usage: Usage | None  # None for cache hits and the rule mock (no model call)
    cache: str  # "hit", "miss", or "off"
