from datetime import datetime, timedelta, timezone

from app.quota import DailyQuota
from tests.test_api import BODY


def test_quota_resets_each_utc_day():
    now = [datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)]
    q = DailyQuota(2, clock=lambda: now[0])
    assert q.try_take() and q.try_take() and not q.try_take()
    now[0] += timedelta(hours=2)
    assert q.try_take()


def test_create_scenario_rate_limited(client):
    from app.main import app
    from app.quota import DailyQuota

    app.state.quota = DailyQuota(1)
    assert client.post("/v1/scenarios", json=BODY).status_code == 201
    response = client.post("/v1/scenarios", json=BODY)
    assert response.status_code == 429 and response.json()["error"]["code"] == "RATE_LIMITED"


def test_population_cap(client):
    from app.main import app

    app.state.max_population_size = 1000
    response = client.post("/v1/scenarios", json=BODY | {"population_size": 5000})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["field"] == "population_size"
