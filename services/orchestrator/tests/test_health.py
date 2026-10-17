from fastapi.testclient import TestClient

from app.main import SERVICE_VERSION, app


def test_health(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "ebc-cloud-dev-03")
    response = TestClient(app).get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "orchestrator",
        "version": SERVICE_VERSION,
        "project": "ebc-cloud-dev-03",
    }
