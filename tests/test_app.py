from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthcheck() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_modules_overview_contains_expected_modules() -> None:
    response = client.get("/api/v1/modules")

    assert response.status_code == 200
    payload = response.json()
    module_names = {module["name"] for module in payload}

    assert module_names == {
        "auth",
        "content",
        "snapshots",
        "search",
        "vectorization",
        "llm",
    }
