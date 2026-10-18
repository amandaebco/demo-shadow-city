import time

from tests.conftest import FakeGeminiModels, fake_client

BODY = {
    "name": "Central parking +100%",
    "base_scenario_id": None,
    "seed": 42,
    "population_size": 50,
    "policies": [{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
    "events": [{"type": "flood", "area_id": "jakarta_utara", "start_tick": 60, "end_tick": 120, "depth_cm": 40}],
}


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_health(client):
    assert client.get("/v1/health").json()["status"] == "ok"


def test_create_scenario_generates_population_and_publishes(client, deps):
    response = client.post("/v1/scenarios", json=BODY)
    assert response.status_code == 201
    scenario_id = response.json()["scenario_id"]
    assert scenario_id.startswith("s_central_parking_100_")

    assert wait_for(lambda: deps.publisher.started)
    assert deps.publisher.started == [{"scenario_id": scenario_id, "seed": 42}]
    scenario = client.get(f"/v1/scenarios/{scenario_id}").json()
    assert scenario["population_id"] == "pop_s42_n50"
    assert scenario["status"] == "generating_population"
    assert scenario["policies"] == BODY["policies"]
    assert deps.store.count_personas("pop_s42_n50") == 50

    persona = client.get("/v1/personas/p_s42_n50_00000").json()
    assert persona["population_id"] == "pop_s42_n50"
    assert persona["memory"] == []


def test_second_scenario_reuses_population(client, deps):
    client.post("/v1/scenarios", json=BODY)
    assert wait_for(lambda: len(deps.publisher.started) == 1)
    calls = deps.models.calls
    base_id = deps.publisher.started[0]["scenario_id"]
    client.post("/v1/scenarios", json=BODY | {"name": "Variant", "base_scenario_id": base_id})
    assert wait_for(lambda: len(deps.publisher.started) == 2)
    assert deps.models.calls == calls


def test_population_failure_marks_scenario_failed(client, deps):
    deps.generator._client = fake_client(FakeGeminiModels(fail=True))
    scenario_id = client.post("/v1/scenarios", json=BODY).json()["scenario_id"]
    assert wait_for(lambda: deps.publisher.failed)
    assert deps.publisher.failed[0]["stage"] == "population"
    assert deps.store.scenarios[scenario_id]["status"] == "failed"
    assert deps.publisher.started == []


def test_invalid_population_size(client):
    response = client.post("/v1/scenarios", json=BODY | {"population_size": 5})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "INVALID_SCENARIO"
    assert error["details"]["field"] == "population_size"


def test_unknown_base_scenario(client):
    response = client.post("/v1/scenarios", json=BODY | {"base_scenario_id": "s_missing"})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["field"] == "base_scenario_id"


def test_event_end_before_start(client):
    bad = BODY | {"events": [BODY["events"][0] | {"start_tick": 100, "end_tick": 50}]}
    assert client.post("/v1/scenarios", json=bad).json()["error"]["code"] == "INVALID_SCENARIO"


def test_not_found(client):
    for path in ["/v1/scenarios/s_x", "/v1/scenarios/s_x/metrics", "/v1/personas/p_x"]:
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_and_metrics(client, deps):
    scenario_id = client.post("/v1/scenarios", json=BODY).json()["scenario_id"]
    deps.store.metrics[scenario_id] = {"scenario_id": scenario_id, "by_kelurahan": [], "by_income_band": [], "citywide": {}}
    assert [s["scenario_id"] for s in client.get("/v1/scenarios").json()] == [scenario_id]
    assert client.get(f"/v1/scenarios/{scenario_id}/metrics").json()["scenario_id"] == scenario_id


def test_report_waits_for_metrics(client):
    scenario_id = client.post("/v1/scenarios", json=BODY).json()["scenario_id"]
    response = client.get(f"/v1/scenarios/{scenario_id}/report")
    assert response.status_code == 404
    assert "metrics" in response.json()["error"]["message"]


def test_report_generated_once_then_cached(client, deps):
    scenario_id = client.post("/v1/scenarios", json=BODY).json()["scenario_id"]
    deps.store.metrics[scenario_id] = {"scenario_id": scenario_id, "citywide": {}}
    first = client.get(f"/v1/scenarios/{scenario_id}/report")
    assert first.status_code == 200
    assert first.json()["generated_by"] == "gemini-system-two"
    assert client.get(f"/v1/scenarios/{scenario_id}/report").json() == first.json()
    assert deps.report_writer.calls == 1


def test_report_model_failure(client, deps):
    deps.report_writer.fail = True
    scenario_id = client.post("/v1/scenarios", json=BODY).json()["scenario_id"]
    deps.store.metrics[scenario_id] = {"scenario_id": scenario_id}
    response = client.get(f"/v1/scenarios/{scenario_id}/report")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_report_unknown_scenario(client):
    assert client.get("/v1/scenarios/s_missing/report").json()["error"]["code"] == "NOT_FOUND"


def make_pair(client, deps):
    base_id = client.post("/v1/scenarios", json=BODY | {"name": "Baseline", "policies": [], "events": []}).json()["scenario_id"]
    variant_id = client.post("/v1/scenarios", json=BODY | {"base_scenario_id": base_id}).json()["scenario_id"]
    return base_id, variant_id


def test_compare_defaults_to_scenario_baseline(client, deps):
    base_id, variant_id = make_pair(client, deps)
    deps.store.metrics[base_id] = {"scenario_id": base_id, "citywide": {"avg_travel_min": 40.0}}
    deps.store.metrics[variant_id] = {"scenario_id": variant_id, "citywide": {"avg_travel_min": 43.0}}
    body = client.get(f"/v1/scenarios/{variant_id}/compare").json()
    assert body == {"base": deps.store.metrics[base_id], "variant": deps.store.metrics[variant_id]}
    assert client.get(f"/v1/scenarios/{base_id}/compare?base={variant_id}").json()["base"]["scenario_id"] == variant_id


def test_compare_errors(client, deps):
    base_id, variant_id = make_pair(client, deps)
    no_base = client.get(f"/v1/scenarios/{base_id}/compare")
    assert no_base.status_code == 400 and no_base.json()["error"]["details"]["field"] == "base"
    missing = client.get(f"/v1/scenarios/{variant_id}/compare")
    assert missing.status_code == 404 and variant_id in missing.json()["error"]["message"]
    assert client.get("/v1/scenarios/s_nope/compare?base=s_x").status_code == 404


def test_report_uses_baseline_once_its_metrics_exist(client, deps):
    base_id, variant_id = make_pair(client, deps)
    deps.store.metrics[variant_id] = {"scenario_id": variant_id}
    waiting = client.get(f"/v1/scenarios/{variant_id}/report")
    assert waiting.status_code == 404 and "baseline" in waiting.json()["error"]["message"]
    deps.store.metrics[base_id] = {"scenario_id": base_id}
    assert client.get(f"/v1/scenarios/{variant_id}/report").status_code == 200
    assert deps.report_writer.last_base["scenario_id"] == base_id


def test_verification_waits_for_metrics_then_is_stored(client, deps):
    scenario_id = client.post("/v1/scenarios", json=BODY).json()["scenario_id"]
    assert wait_for(lambda: deps.publisher.started)
    assert client.get(f"/v1/scenarios/{scenario_id}/verification").status_code == 404
    deps.store.metrics[scenario_id] = {"scenario_id": scenario_id, "citywide": {}}
    first = client.get(f"/v1/scenarios/{scenario_id}/verification").json()
    assert first["persona_count"] == 50
    assert client.get(f"/v1/scenarios/{scenario_id}/verification").json() == first
    assert deps.verifier.calls == 1


def test_new_population_is_clustered(client, deps):
    client.post("/v1/scenarios", json=BODY | {"population_size": 60})
    assert wait_for(lambda: deps.publisher.started)
    personas = [p for p in deps.store.personas.values() if p["population_id"] == "pop_s42_n60"]
    clusters = {}
    for p in personas:
        clusters.setdefault(p["cluster_id"], []).append(p["is_cluster_representative"])
    assert len(clusters) < len(personas)  # identical fake profiles share clusters
    assert all(reps.count(True) == 1 for reps in clusters.values())
