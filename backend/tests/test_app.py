from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.api.cache import install_cache_control
from app.core.config import Settings
from app.main import app, configure_cors, create_app

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
    assert response.headers["cache-control"] == "public, max-age=5, stale-while-revalidate=30"


def test_api_responses_default_to_no_store_cache_policy() -> None:
    response = client.get("/api/v1/modules")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"


def test_api_cache_middleware_preserves_explicit_cache_policy() -> None:
    cache_app = create_app()

    @cache_app.get("/api/v1/cacheable-test")
    async def cacheable_test(response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "public, max-age=60"
        return {"status": "ok"}

    cache_client = TestClient(cache_app)
    response = cache_client.get("/api/v1/cacheable-test")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"


def test_api_cache_middleware_caches_successful_private_files() -> None:
    cache_app = FastAPI()
    install_cache_control(cache_app, api_prefix="/api/v1")

    @cache_app.get("/api/v1/notes/note/asset/image")
    async def asset() -> Response:
        return Response(content=b"image", media_type="image/png")

    cache_client = TestClient(cache_app)
    response = cache_client.get(
        "/api/v1/notes/note/asset/image",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == (
        "private, max-age=86400, stale-while-revalidate=604800"
    )
    assert response.headers["vary"] == "Authorization, Cookie"
