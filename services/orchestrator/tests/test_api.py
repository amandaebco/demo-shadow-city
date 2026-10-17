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
