from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app, configure_cors

client = TestClient(app)


def test_settings_read_cors_values_from_env(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "vkr_api")
    monkeypatch.setenv("POSTGRES_USER", "app")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_DB", "2")
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        '["http://localhost:3000","http://127.0.0.1:5173"]',
    )
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGIN_REGEX",
        r"https://([a-zA-Z0-9-]+\.)*temaa\.space",
    )

    settings = Settings()

    assert settings.cors_allowed_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]
    assert settings.cors_allow_origin_regex == r"https://([a-zA-Z0-9-]+\.)*temaa\.space"
    assert settings.sqlalchemy_database_uri == (
        "postgresql+asyncpg://app:secret@db.internal:5433/vkr_api"
    )
    assert settings.redis_url == "redis://redis.internal:6380/2"

    get_settings.cache_clear()


def test_settings_uses_libreoffice_for_office_conversion_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SNAPSHOT_OFFICE_CONVERTER_COMMAND", raising=False)

    assert Settings().snapshot_office_converter_command == "libreoffice"


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


def test_swagger_ui_is_available() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text


def test_modules_overview_contains_expected_modules() -> None:
    response = client.get("/api/v1/modules")

    assert response.status_code == 200
    payload = response.json()
    module_names = {module["name"] for module in payload}

    assert module_names == {
        "auth",
        "content",
        "snapshots",
        "tags",
        "taxonomy",
        "search",
        "vectorization",
        "llm",
    }


def test_openapi_documents_auth_contracts() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    telegram_callback_operation = schema["paths"]["/api/v1/auth/telegram-callback"]["get"]
    telegram_code_operation = schema["paths"]["/api/v1/auth/telegram-code"]["post"]
    telegram_login_operation = schema["paths"]["/api/v1/auth/telegram-login"]["post"]
    refresh_operation = schema["paths"]["/api/v1/auth/refresh"]["post"]
    me_operation = schema["paths"]["/api/v1/auth/me"]["get"]

    assert "/api/v1/auth/register" not in schema["paths"]
    assert "/api/v1/auth/login" not in schema["paths"]
    assert telegram_callback_operation["summary"] == "Telegram redirect callback"
    assert telegram_code_operation["summary"] == "Exchange Telegram login code"
    assert telegram_login_operation["summary"] == "Login with Telegram"
    assert telegram_login_operation["responses"]["401"]["description"] == (
        "Invalid Telegram login data."
    )
    assert (
        refresh_operation["responses"]["401"]["description"] == "Missing or invalid refresh token."
    )
    assert me_operation["responses"]["401"]["description"] == "Missing or invalid access token."
    assert "TelegramLoginRequest" in schema["components"]["schemas"]
    assert "AuthTokensResponse" in schema["components"]["schemas"]
    assert "ErrorResponse" in schema["components"]["schemas"]
    assert "ErrorDetail" in schema["components"]["schemas"]


def test_openapi_uses_bearer_security_scheme_for_authorized_routes() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    security_schemes = schema["components"]["securitySchemes"]
    me_operation = schema["paths"]["/api/v1/auth/me"]["get"]
    notes_operation = schema["paths"]["/api/v1/notes"]["get"]

    assert security_schemes["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert me_operation["security"] == [{"BearerAuth": []}]
    assert notes_operation["security"] == [{"BearerAuth": []}]
    for operation in (me_operation, notes_operation):
        assert not any(
            parameter["in"] == "header" and parameter["name"].lower() == "authorization"
            for parameter in operation.get("parameters", [])
        )
