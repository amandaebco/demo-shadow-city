"""Baseline vs variant comparison (Layer 3, REFERENCE.md §6.6).

All differences are computed here, deterministically, from Track B's metrics (CONTRACT.md §2.5).
The analyst report only interprets them; Gemini never computes numbers.
"""

COUNT_FIELDS = ("stuck_count", "cancelled_count")
TOP_N = 5


def _share_points(base: dict | None, variant: dict | None) -> dict[str, float]:
    """Mode share change in percentage points; a mode missing on one side counts as 0."""
    base, variant = base or {}, variant or {}
    return {
        mode: round((variant.get(mode, 0.0) - base.get(mode, 0.0)) * 100, 1)
        for mode in sorted(set(base) | set(variant))
    }


def diff_group(base: dict, variant: dict) -> dict:
    delta = {}
    if "avg_travel_min" in base and "avg_travel_min" in variant:
        delta["avg_travel_min"] = round(variant["avg_travel_min"] - base["avg_travel_min"], 1)
    if "avg_cost_idr" in base and "avg_cost_idr" in variant:
        delta["avg_cost_idr"] = int(round(variant["avg_cost_idr"] - base["avg_cost_idr"]))
    for field in COUNT_FIELDS:
        if field in base and field in variant:
            delta[field] = int(variant[field] - base[field])
    if "mode_share" in base or "mode_share" in variant:
        delta["mode_share_pp"] = _share_points(base.get("mode_share"), variant.get("mode_share"))
    return delta


def _diff_list(base_rows: list[dict], variant_rows: list[dict], key: str) -> tuple[list[dict], list[str], list[str]]:
    base_by = {row[key]: row for row in base_rows or []}
    variant_by = {row[key]: row for row in variant_rows or []}
    common = sorted(set(base_by) & set(variant_by))
    rows = [{key: name, **diff_group(base_by[name], variant_by[name])} for name in common]
    return rows, sorted(set(base_by) - set(variant_by)), sorted(set(variant_by) - set(base_by))


def _top(rows: list[dict], key: str, field: str, largest: bool) -> list[dict]:
    present = [r for r in rows if field in r]
    ordered = sorted(present, key=lambda r: (r[field], r[key]), reverse=largest)
    return [{key: r[key], field: r[field]} for r in ordered[:TOP_N] if (r[field] > 0 if largest else r[field] < 0)]


def compute_deltas(base: dict, variant: dict) -> dict:
    """Variant minus base, for citywide, each kelurahan, and each income band."""
    kelurahan, only_base, only_variant = _diff_list(base.get("by_kelurahan"), variant.get("by_kelurahan"), "kelurahan")
    income, _, _ = _diff_list(base.get("by_income_band"), variant.get("by_income_band"), "income_band")
    return {
        "citywide": diff_group(base.get("citywide", {}), variant.get("citywide", {})),
        "by_income_band": income,
        "by_kelurahan": kelurahan,
        "kelurahan_only_in_base": only_base,
        "kelurahan_only_in_variant": only_variant,
        "largest_travel_time_increase": _top(kelurahan, "kelurahan", "avg_travel_min", largest=True),
        "largest_travel_time_decrease": _top(kelurahan, "kelurahan", "avg_travel_min", largest=False),
        "largest_cost_increase": _top(kelurahan, "kelurahan", "avg_cost_idr", largest=True),
        "largest_cost_decrease": _top(kelurahan, "kelurahan", "avg_cost_idr", largest=False),
    }


def comparable(base_scenario: dict, variant_scenario: dict) -> list[str]:
    """Reasons the two runs are not a clean counterfactual; empty when they are."""
    problems = []
    for field in ("seed", "population_size", "population_id"):
        if base_scenario.get(field) != variant_scenario.get(field):
            problems.append(f"{field} differs ({base_scenario.get(field)} vs {variant_scenario.get(field)})")
    return problems


def scenario_changes(base_scenario: dict, variant_scenario: dict) -> dict:
    """Policies and events present in one scenario but not the other."""
    def key(item: dict) -> str:
        return repr(sorted(item.items()))

    changes = {}
    for field in ("policies", "events"):
        base_items = {key(i): i for i in base_scenario.get(field, [])}
        variant_items = {key(i): i for i in variant_scenario.get(field, [])}
        changes[f"{field}_added"] = [variant_items[k] for k in sorted(set(variant_items) - set(base_items))]
        changes[f"{field}_removed"] = [base_items[k] for k in sorted(set(base_items) - set(variant_items))]
    return changes
