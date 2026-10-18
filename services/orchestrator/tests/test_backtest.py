from app.backtest import direction, evaluate_backtest, transit_share

DEF = {"backtest_id": "b_0001", "scenario_id": "s_rp1", "base_scenario_id": "s_base",
       "reference_direction": "increase", "reference_value": None, "reference_source": "ANTARA"}
BASE = {"citywide": {"mode_share": {"transjakarta": 0.237, "krl": 0.063, "mrt": 0.02, "motorcycle": 0.342}}}
RP1 = {"citywide": {"mode_share": {"transjakarta": 0.30, "krl": 0.06, "mrt": 0.03, "motorcycle": 0.30}}}


def test_transit_share_and_direction():
    assert round(transit_share(BASE), 3) == 0.32
    assert direction(2.0) == "increase" and direction(-0.6) == "decrease" and direction(0.3) == "no change"


def test_direction_match_with_pending_reference_value():
    r = evaluate_backtest(DEF, RP1, BASE)
    assert r["simulated_value"] == 7.0 and r["simulated_direction"] == "increase"
    assert r["direction_match"] is True and r["reference_value"] is None


def test_mismatch_and_missing_metrics():
    assert evaluate_backtest(DEF, BASE, RP1)["direction_match"] is False
    pending = evaluate_backtest(DEF, None, BASE)
    assert pending["simulated_value"] is None and pending["direction_match"] is None


def test_endpoint(client, deps):
    assert client.get("/v1/backtests/b_0001").status_code == 404
    deps.store.backtests["b_0001"] = DEF
    deps.store.metrics.update({"s_rp1": RP1, "s_base": BASE})
    body = client.get("/v1/backtests/b_0001").json()
    assert body["direction_match"] is True and body["simulated_value"] == 7.0
