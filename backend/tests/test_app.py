from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, configure_cors, create_app

client = TestClient(app)


def cors_client() -> TestClient:
    cors_app = FastAPI()
    configure_cors(cors_app, Settings(_env_file=None, cors_allowed_origins=["https://app.example"]))  # type: ignore[call-arg]

    @cors_app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(cors_app)


def preflight(test_client: TestClient, origin: str) -> Response:
    return test_client.options(  # type: ignore[return-value]
        "/ping", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )


def test_cors_allows_configured_origin_with_credentials() -> None:
    response = preflight(cors_client(), "https://app.example")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_unknown_origin() -> None:
    response = preflight(cors_client(), "https://evil.example")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_liveness_is_public_and_briefly_cacheable() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"].startswith("public")


def test_api_errors_default_to_no_store() -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert "no-store" in response.headers["cache-control"]


def test_explicit_cache_policy_is_preserved() -> None:
    cache_app = create_app()

    @cache_app.get("/api/v1/cacheable-test")
    async def cacheable_test(response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "public, max-age=60"
        return {"status": "ok"}

    response = TestClient(cache_app).get("/api/v1/cacheable-test")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"


def test_admin_api_requires_authentication() -> None:
    with TestClient(create_app()) as lifespan_client:
        assert lifespan_client.get("/api/v1/admin/overview").status_code == 401
