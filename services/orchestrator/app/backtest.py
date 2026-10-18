"""Backtest against a real event (Layer 7, CONTRACT.md §8, §10.5).

A backtest definition (Firestore `backtests/{id}`, written by Track A) names a scenario that
recreates a real day and its baseline. The simulated value is computed here from both scenarios'
metrics; the reference is what a cited source reports. Without a published figure, only the
direction is compared and reference_value stays null ("reference pending").
"""

TRANSIT_MODES = ("transjakarta", "mrt", "krl")
NO_CHANGE_PP = 0.5  # changes smaller than this (percentage points) count as "no change"


def transit_share(metrics: dict) -> float:
    share = (metrics.get("citywide") or {}).get("mode_share") or {}
    return sum(share.get(mode, 0.0) for mode in TRANSIT_MODES)


def direction(change_pp: float) -> str:
    if change_pp > NO_CHANGE_PP:
        return "increase"
    if change_pp < -NO_CHANGE_PP:
        return "decrease"
    return "no change"


def evaluate_backtest(definition: dict, variant_metrics: dict | None, base_metrics: dict | None) -> dict:
    result = {
        "backtest_id": definition["backtest_id"],
        "description": definition.get("description"),
        "scenario_id": definition.get("scenario_id"),
        "base_scenario_id": definition.get("base_scenario_id"),
        "metric": definition.get("metric", "transit_mode_share_change"),
        "simulated_value": None,
        "simulated_direction": None,
        "reference_value": definition.get("reference_value"),
        "reference_direction": definition.get("reference_direction"),
        "reference_source": definition.get("reference_source"),
        "direction_match": None,
        "notes": definition.get("notes"),
    }
    if variant_metrics and base_metrics:
        change_pp = round((transit_share(variant_metrics) - transit_share(base_metrics)) * 100, 1)
        result["simulated_value"] = change_pp
        result["simulated_direction"] = direction(change_pp)
        if result["reference_direction"]:
            result["direction_match"] = result["simulated_direction"] == result["reference_direction"]
    return result
