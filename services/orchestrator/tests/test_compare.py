from app.compare import comparable, compute_deltas, diff_group, scenario_changes

BASE = {
    "citywide": {"avg_travel_min": 40.0, "avg_cost_idr": 12000, "stuck_count": 0,
                 "mode_share": {"car": 0.10, "krl": 0.30}},
    "by_kelurahan": [
        {"kelurahan": "Pluit", "avg_travel_min": 50.0, "avg_cost_idr": 20000, "stuck_count": 0},
        {"kelurahan": "Gambir", "avg_travel_min": 30.0, "avg_cost_idr": 9000, "stuck_count": 0},
        {"kelurahan": "Koja", "avg_travel_min": 45.0, "avg_cost_idr": 8000, "stuck_count": 0},
    ],
    "by_income_band": [{"income_band": "low", "avg_travel_min": 41.0, "avg_cost_idr": 7000, "stuck_count": 0}],
}
VARIANT = {
    "citywide": {"avg_travel_min": 43.5, "avg_cost_idr": 11500, "stuck_count": 3,
                 "mode_share": {"car": 0.04, "krl": 0.33, "mrt": 0.05}},
    "by_kelurahan": [
        {"kelurahan": "Pluit", "avg_travel_min": 61.2, "avg_cost_idr": 18000, "stuck_count": 3},
        {"kelurahan": "Gambir", "avg_travel_min": 29.0, "avg_cost_idr": 12500, "stuck_count": 0},
        {"kelurahan": "Cilincing", "avg_travel_min": 55.0, "avg_cost_idr": 9000, "stuck_count": 0},
    ],
    "by_income_band": [{"income_band": "low", "avg_travel_min": 47.0, "avg_cost_idr": 6900, "stuck_count": 2}],
}


def test_citywide_delta_and_mode_share_points():
    d = compute_deltas(BASE, VARIANT)["citywide"]
    assert d["avg_travel_min"] == 3.5
    assert d["avg_cost_idr"] == -500
    assert d["stuck_count"] == 3
    assert d["mode_share_pp"] == {"car": -6.0, "krl": 3.0, "mrt": 5.0}


def test_kelurahan_rows_and_membership():
    d = compute_deltas(BASE, VARIANT)
    assert [r["kelurahan"] for r in d["by_kelurahan"]] == ["Gambir", "Pluit"]
    assert d["kelurahan_only_in_base"] == ["Koja"]
    assert d["kelurahan_only_in_variant"] == ["Cilincing"]


def test_top_lists_only_include_real_changes():
    d = compute_deltas(BASE, VARIANT)
    assert d["largest_travel_time_increase"] == [{"kelurahan": "Pluit", "avg_travel_min": 11.2}]
    assert d["largest_travel_time_decrease"] == [{"kelurahan": "Gambir", "avg_travel_min": -1.0}]
    assert d["largest_cost_increase"] == [{"kelurahan": "Gambir", "avg_cost_idr": 3500}]
    assert d["largest_cost_decrease"] == [{"kelurahan": "Pluit", "avg_cost_idr": -2000}]


def test_income_band_delta():
    row = compute_deltas(BASE, VARIANT)["by_income_band"][0]
    assert row == {"income_band": "low", "avg_travel_min": 6.0, "avg_cost_idr": -100, "stuck_count": 2}


def test_missing_fields_are_skipped():
    assert diff_group({"avg_travel_min": 1.0}, {}) == {}


def test_comparable_requires_same_population():
    a = {"seed": 42, "population_size": 50, "population_id": "pop_s42_n50"}
    assert comparable(a, dict(a)) == []
    assert comparable(a, a | {"seed": 7}) == ["seed differs (42 vs 7)"]


def test_scenario_changes():
    base = {"policies": [], "events": []}
    variant = {"policies": [{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
               "events": [{"type": "flood", "area_id": "jakarta_utara"}]}
    changes = scenario_changes(base, variant)
    assert changes["policies_added"] == variant["policies"]
    assert changes["events_added"] == variant["events"]
    assert changes["policies_removed"] == [] and changes["events_removed"] == []


def test_kecamatan_rollup_is_resident_weighted():
    from app.compare import KECAMATAN_OF, kecamatan_metrics

    a, b = [k for k, kec in KECAMATAN_OF.items() if kec == "Penjaringan"][:2]
    metrics = {"by_kelurahan": [
        {"kelurahan": a, "avg_travel_min": 60.0, "avg_cost_idr": 10000, "stuck_count": 2, "mode_share": {"car": 1.0}},
        {"kelurahan": b, "avg_travel_min": 30.0, "avg_cost_idr": 4000, "stuck_count": 1, "mode_share": {"krl": 1.0}},
        {"kelurahan": "Nowhere", "avg_travel_min": 99.0, "avg_cost_idr": 1, "stuck_count": 9},
    ]}
    (row,) = kecamatan_metrics(metrics, {a: 3, b: 1, "Nowhere": 5})
    assert row["kecamatan"] == "Penjaringan" and row["residents"] == 4
    assert row["avg_travel_min"] == 52.5  # (60*3 + 30*1) / 4
    assert row["avg_cost_idr"] == 8500
    assert row["stuck_count"] == 3
    assert row["mode_share"] == {"car": 0.75, "krl": 0.25}


def test_small_kelurahan_are_not_ranked_but_kecamatan_are():
    from app.compare import KECAMATAN_OF

    small, big = [k for k, kec in KECAMATAN_OF.items() if kec == "Cilincing"][:2]
    base = {"citywide": {}, "by_kelurahan": [
        {"kelurahan": small, "avg_travel_min": 30.0, "avg_cost_idr": 5000, "stuck_count": 0},
        {"kelurahan": big, "avg_travel_min": 40.0, "avg_cost_idr": 5000, "stuck_count": 0}]}
    variant = {"citywide": {}, "by_kelurahan": [
        {"kelurahan": small, "avg_travel_min": 90.0, "avg_cost_idr": 5000, "stuck_count": 1},
        {"kelurahan": big, "avg_travel_min": 50.0, "avg_cost_idr": 5000, "stuck_count": 4}]}
    d = compute_deltas(base, variant, {small: 2, big: 12})
    assert [r["kelurahan"] for r in d["kelurahan_with_enough_residents"]] == [big]
    assert "largest_travel_time_increase" not in d  # no unweighted kelurahan ranking
    (top,) = d["kecamatan_largest_travel_time_increase"]
    assert top["kecamatan"] == "Cilincing" and top["residents"] == 14
    assert top["avg_travel_min"] == round((2 * 90 + 12 * 50) / 14 - (2 * 30 + 12 * 40) / 14, 1)
    assert d["kecamatan_largest_stuck_increase"][0]["stuck_count"] == 5
