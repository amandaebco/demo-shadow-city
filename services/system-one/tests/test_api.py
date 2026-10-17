import copy


def test_health(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_version": "rule-mock-v0"}


def test_decide_contract_example(client, item):
    response = client.post("/v1/decide", json={"items": [item]})
    assert response.status_code == 200
    (result,) = response.json()["items"]
    assert result["request_id"] == "q_000981"
    assert result["chosen"] == "transjakarta"
    assert result["decided_by"] == "rule-fallback"
    assert set(result) == {
        "request_id", "decision_id", "probabilities", "chosen",
        "reason_short", "decided_by", "model_version", "latency_ms",
    }


def test_decide_keeps_request_order(client, item):
    items = []
    for i in range(5):
        it = copy.deepcopy(item)
        it["request_id"] = f"q_{i:06d}"
        items.append(it)
    response = client.post("/v1/decide", json={"items": items})
    assert [r["request_id"] for r in response.json()["items"]] == [it["request_id"] for it in items]


def test_decide_accepts_max_batch(client, item):
    response = client.post("/v1/decide", json={"items": [item] * 256})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 256


def assert_invalid(response):
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["message"]


def test_decide_rejects_oversized_batch(client, item):
    assert_invalid(client.post("/v1/decide", json={"items": [item] * 257}))


def test_decide_rejects_empty_batch(client):
    assert_invalid(client.post("/v1/decide", json={"items": []}))


def test_decide_rejects_missing_option_detail(client, item):
    del item["context"]["options_detail"]["krl"]
    assert_invalid(client.post("/v1/decide", json={"items": [item]}))


def test_decide_rejects_unknown_mode(client, item):
    item["options"].append("helicopter")
    assert_invalid(client.post("/v1/decide", json={"items": [item]}))


def test_decide_rejects_out_of_range_sensitivity(client, item):
    item["context"]["cost_sensitivity"] = 1.5
    assert_invalid(client.post("/v1/decide", json={"items": [item]}))


def test_decide_rejects_unsupported_question_type(client, item):
    item["question_type"] = "route_choice"
    assert_invalid(client.post("/v1/decide", json={"items": [item]}))


def test_unknown_path_uses_contract_error_shape(client):
    response = client.get("/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
