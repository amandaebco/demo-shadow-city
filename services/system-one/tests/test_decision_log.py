import json
from types import SimpleNamespace

from app.costs import Usage
from app.decision_log import BigQueryDecisionLog, decision_row
from app.models import DecisionRequestItem
from app.rules import decide


def test_row_has_full_evidence(item):
    req = DecisionRequestItem.model_validate(item)
    resp = decide(req)
    row = decision_row(req, resp, Usage("gemini-x", 500, 80, 400, 0.002), "miss")
    assert row["scenario_id"] == "s_parking_up_flood_north" and row["tick"] == 84
    assert row["options"] == ["motorcycle", "transjakarta", "krl", "ojol"]
    assert row["chosen"] == "transjakarta" and row["cache"] == "miss"
    assert (row["prompt_tokens"], row["thoughts_tokens"], row["cost_usd"]) == (500, 400, 0.002)
    assert json.loads(row["request"])["context"]["options_detail"]["krl"]["est_minutes"] == 65
    assert json.loads(row["probabilities"])["transjakarta"] == 1.0


def test_row_without_usage(item):
    req = DecisionRequestItem.model_validate(item)
    row = decision_row(req, decide(req), None, "hit")
    assert row["prompt_tokens"] is None and row["cost_usd"] is None and row["cache"] == "hit"


def test_write_never_raises():
    class Failing:
        def insert_rows_json(self, table, rows):
            raise RuntimeError("bq down")

    BigQueryDecisionLog(Failing(), "p.d.decisions").write([{"a": 1}])
    rejected = SimpleNamespace(insert_rows_json=lambda table, rows: [{"index": 0, "errors": ["bad"]}])
    BigQueryDecisionLog(rejected, "p.d.decisions").write([{"a": 1}])


def test_decide_endpoint_writes_one_row_per_item(client, item, decision_log):
    items = [dict(item, request_id=f"q_{i}") for i in range(3)]
    assert client.post("/v1/decide", json={"items": items}).status_code == 200
    assert [r["request_id"] for r in decision_log.rows] == ["q_0", "q_1", "q_2"]
