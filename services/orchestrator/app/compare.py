"""Baseline vs variant comparison (Layer 3, REFERENCE.md §6.6).

All differences are computed here, deterministically, from Track B's metrics (CONTRACT.md §2.5).
The analyst report only interprets them; Gemini never computes numbers.
"""

from app.kelurahan import HOME_KELURAHAN

COUNT_FIELDS = ("stuck_count", "cancelled_count")
TOP_N = 5
# With ~1,000 residents over ~260 kelurahan, a kelurahan holds ~4 people: too few to name.
MIN_AREA_RESIDENTS = 10
KECAMATAN_OF = {kelurahan: kecamatan for kelurahan, kecamatan, _, _ in HOME_KELURAHAN}


def kecamatan_metrics(metrics: dict, counts: dict[str, int]) -> list[dict]:
    """Roll kelurahan rows up to kecamatan, weighting averages by residents per kelurahan."""
    totals: dict[str, dict] = {}
    for row in metrics.get("by_kelurahan") or []:
        residents = counts.get(row.get("kelurahan"), 0)
        kecamatan = KECAMATAN_OF.get(row.get("kelurahan"))
        if not residents or not kecamatan:
            continue
        t = totals.setdefault(kecamatan, {"residents": 0, "travel": 0.0, "cost": 0.0, "stuck_count": 0,
                                          "cancelled_count": 0, "share": {}})
        t["residents"] += residents
        t["travel"] += row.get("avg_travel_min", 0.0) * residents
        t["cost"] += row.get("avg_cost_idr", 0) * residents
        for field in COUNT_FIELDS:
            t[field] += row.get(field, 0)
        for mode, share in (row.get("mode_share") or {}).items():
            t["share"][mode] = t["share"].get(mode, 0.0) + share * residents
    return [
        {
            "kecamatan": name,
            "residents": t["residents"],
            "avg_travel_min": round(t["travel"] / t["residents"], 1),
            "avg_cost_idr": int(round(t["cost"] / t["residents"])),
            "stuck_count": t["stuck_count"],
            "cancelled_count": t["cancelled_count"],
            "mode_share": {m: round(v / t["residents"], 3) for m, v in sorted(t["share"].items())},
        }
        for name, t in sorted(totals.items())
    ]


def area_view(metrics: dict, counts: dict[str, int]) -> dict:
    """One scenario's areas: kecamatan rows, plus only the kelurahan with enough residents."""
    kelurahan = [
        {**row, "residents": counts[row["kelurahan"]]}
        for row in metrics.get("by_kelurahan") or []
        if counts.get(row.get("kelurahan"), 0) >= MIN_AREA_RESIDENTS
    ]
    return {
        "by_kecamatan": kecamatan_metrics(metrics, counts),
        "kelurahan_with_enough_residents": kelurahan,
        "min_residents_to_name_an_area": MIN_AREA_RESIDENTS,
    }


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


def compute_deltas(base: dict, variant: dict, counts: dict[str, int] | None = None) -> dict:
    """Variant minus base, for citywide, each kelurahan, and each income band.

    With resident counts per kelurahan, area results are made robust: kecamatan rows
    (resident-weighted) are added, and only areas with enough residents are ranked.
    """
    kelurahan, only_base, only_variant = _diff_list(base.get("by_kelurahan"), variant.get("by_kelurahan"), "kelurahan")
    income, _, _ = _diff_list(base.get("by_income_band"), variant.get("by_income_band"), "income_band")
    if counts is not None:
        return _deltas_by_area(base, variant, counts, kelurahan, income)
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


def _deltas_by_area(base: dict, variant: dict, counts: dict[str, int], kelurahan: list[dict], income: list[dict]) -> dict:
    kecamatan, _, _ = _diff_list(kecamatan_metrics(base, counts), kecamatan_metrics(variant, counts), "kecamatan")
    residents = {row["kecamatan"]: row["residents"] for row in kecamatan_metrics(base, counts)}
    kecamatan = [{**row, "residents": residents.get(row["kecamatan"], 0)} for row in kecamatan]
    named_kelurahan = [{**row, "residents": counts.get(row["kelurahan"], 0)} for row in kelurahan
                       if counts.get(row["kelurahan"], 0) >= MIN_AREA_RESIDENTS]
    ranked_kecamatan = [row for row in kecamatan if row["residents"] >= MIN_AREA_RESIDENTS]

    def top(rows, key, field, largest):
        picked = _top(rows, key, field, largest)
        by_name = {r[key]: r["residents"] for r in rows}
        return [{**r, "residents": by_name[r[key]]} for r in picked]

    return {
        "citywide": diff_group(base.get("citywide", {}), variant.get("citywide", {})),
        "by_income_band": income,
        "by_kecamatan": kecamatan,
        "kelurahan_with_enough_residents": named_kelurahan,
        "min_residents_to_name_an_area": MIN_AREA_RESIDENTS,
        "kecamatan_largest_travel_time_increase": top(ranked_kecamatan, "kecamatan", "avg_travel_min", True),
        "kecamatan_largest_travel_time_decrease": top(ranked_kecamatan, "kecamatan", "avg_travel_min", False),
        "kecamatan_largest_cost_increase": top(ranked_kecamatan, "kecamatan", "avg_cost_idr", True),
        "kecamatan_largest_cost_decrease": top(ranked_kecamatan, "kecamatan", "avg_cost_idr", False),
        "kecamatan_largest_stuck_increase": top(ranked_kecamatan, "kecamatan", "stuck_count", True),
    }
