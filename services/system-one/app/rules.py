"""Rule-based mock of System One (CONTRACT.md §4.4).

Picks the option with the lowest weighted score of
time_sensitivity * est_minutes + cost_sensitivity * cost_idr, where minutes and cost
are each min-max normalized across the item's options. The result is fully
deterministic: same request, same response (except latency_ms).
"""

import hashlib
import time

from app.models import (
    DecidedBy,
    DecisionRequestItem,
    DecisionResponseItem,
    Mode,
    truncate_reason,
)

MODEL_VERSION = "rule-mock-v0"


def normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. All-equal values normalize to 0."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def score_options(item: DecisionRequestItem) -> dict[Mode, float]:
    """Weighted score per option; lower is better."""
    ctx = item.context
    details = [ctx.options_detail[o] for o in item.options]
    minutes = normalize([d.est_minutes for d in details])
    costs = normalize([float(d.cost_idr) for d in details])
    return {
        option: ctx.time_sensitivity * m + ctx.cost_sensitivity * c
        for option, m, c in zip(item.options, minutes, costs)
    }


def pick_option(scores: dict[Mode, float]) -> Mode:
    """Lowest score wins; ties go to the option listed first (dicts keep request order)."""
    return min(scores, key=lambda option: scores[option])


def decision_id_for(request_id: str) -> str:
    return "d_" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:12]


def reason_for(item: DecisionRequestItem, chosen: Mode) -> str:
    detail = item.context.options_detail[chosen]
    reason = (
        f"Rule mock: {chosen.value} has the lowest weighted time and cost "
        f"({detail.est_minutes:g} min, {detail.cost_idr} IDR)."
    )
    return truncate_reason(reason)


def decide(item: DecisionRequestItem) -> DecisionResponseItem:
    started = time.perf_counter()
    scores = score_options(item)
    chosen = pick_option(scores)
    # The mock is deterministic, so the chosen option gets all probability mass.
    probabilities = {option: (1.0 if option == chosen else 0.0) for option in item.options}
    return DecisionResponseItem(
        request_id=item.request_id,
        decision_id=decision_id_for(item.request_id),
        probabilities=probabilities,
        chosen=chosen,
        reason_short=reason_for(item, chosen),
        decided_by=DecidedBy.rule_fallback,
        model_version=MODEL_VERSION,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
