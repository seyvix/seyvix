from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, configure_cors

client = TestClient(app)


def test_cors_allows_configured_origin_and_credentials() -> None:
    cors_app = FastAPI()
    configure_cors(
        cors_app,
        Settings(
            cors_allowed_origins=["http://localhost:3000"],
            cors_allow_origin_regex=r"https://([a-zA-Z0-9-]+\.)*temaa\.space",
        ),
    )

    @cors_app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    cors_client = TestClient(cors_app)
    response = cors_client.options(
        "/ping",
        headers={
            "Origin": "https://app.temaa.space",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.temaa.space"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_unknown_origin() -> None:
    cors_app = FastAPI()
    configure_cors(
        cors_app,
        Settings(
            cors_allowed_origins=["http://localhost:3000"],
            cors_allow_origin_regex=r"https://([a-zA-Z0-9-]+\.)*temaa\.space",
        ),
    )

    @cors_app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    cors_client = TestClient(cors_app)
    response = cors_client.options(
        "/ping",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_healthcheck() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
