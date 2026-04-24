import asyncio
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, build_session_factory
from app.main import app

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


async def _prepare_database(database_url: str) -> async_sessionmaker:
    engine: AsyncEngine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return build_session_factory(database_url)


def _test_database_url() -> str:
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "vkr_api")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
def auth_client() -> TestClient:
    os.environ["TELEGRAM_BOT_TOKEN"] = TELEGRAM_BOT_TOKEN
    os.environ["TELEGRAM_LOGIN_REDIRECT_URL"] = "http://localhost:3000/auth/telegram"
    get_settings.cache_clear()
    database_url = _test_database_url()
    try:
        app.state.session_factory = asyncio.run(_prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for auth tests: {exc}")

    with TestClient(app) as client:
        yield client
    os.environ.pop("TELEGRAM_LOGIN_REDIRECT_URL", None)
    os.environ.pop("TELEGRAM_DEV_LOGIN_ENABLED", None)
    os.environ.pop("TELEGRAM_DEV_USER_ID", None)
    os.environ.pop("TELEGRAM_DEV_FIRST_NAME", None)
    os.environ.pop("TELEGRAM_DEV_LAST_NAME", None)
    os.environ.pop("TELEGRAM_DEV_USERNAME", None)
    get_settings.cache_clear()


def _telegram_payload(
    *,
    telegram_id: int = 100500,
    first_name: str = "Telegram",
    last_name: str | None = "User",
    username: str | None = "telegram_user",
    photo_url: str | None = "https://t.me/i/userpic/320/example.jpg",
    auth_date: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": telegram_id,
        "first_name": first_name,
        "auth_date": auth_date or int(datetime.now(UTC).timestamp()),
    }
    if last_name is not None:
        payload["last_name"] = last_name
    if username is not None:
        payload["username"] = username
    if photo_url is not None:
        payload["photo_url"] = photo_url

    check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(payload.items()) if key != "hash"
    )
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    payload["hash"] = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return payload


def _telegram_login(auth_client: TestClient, **payload_overrides: object) -> dict[str, object]:
    response = auth_client.post(
        "/api/v1/auth/telegram-login",
        json=_telegram_payload(**payload_overrides),
    )
    assert response.status_code == 200
    return response.json()


def test_telegram_dev_login_is_disabled_by_default(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/api/v1/auth/telegram-dev-login",
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "telegram_dev_login_disabled"


def test_telegram_dev_login_redirects_with_login_code(auth_client: TestClient) -> None:
    os.environ["TELEGRAM_DEV_LOGIN_ENABLED"] = "true"
    os.environ["TELEGRAM_DEV_USER_ID"] = "777001"
    os.environ["TELEGRAM_DEV_FIRST_NAME"] = "Local"
    os.environ["TELEGRAM_DEV_LAST_NAME"] = "Tester"
    os.environ["TELEGRAM_DEV_USERNAME"] = "local_tester"
    get_settings.cache_clear()

    response = auth_client.get(
        "/api/v1/auth/telegram-dev-login",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith("http://localhost:3000/auth/telegram?")
    assert "code=" in response.headers["location"]
    assert auth_client.cookies.get("refresh_token")


def test_telegram_dev_login_code_exchange_returns_configured_user(
    auth_client: TestClient,
) -> None:
    os.environ["TELEGRAM_DEV_LOGIN_ENABLED"] = "true"
    os.environ["TELEGRAM_DEV_USER_ID"] = "777001"
    os.environ["TELEGRAM_DEV_FIRST_NAME"] = "Local"
    os.environ["TELEGRAM_DEV_LAST_NAME"] = "Tester"
    os.environ["TELEGRAM_DEV_USERNAME"] = "local_tester"
    get_settings.cache_clear()
    callback_response = auth_client.get(
        "/api/v1/auth/telegram-dev-login",
        follow_redirects=False,
    )
    code = callback_response.headers["location"].split("code=", maxsplit=1)[1]

    response = auth_client.post(
        "/api/v1/auth/telegram-code",
        json={"code": code},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["telegram_id"] == "777001"
    assert payload["user"]["telegram_username"] == "local_tester"
    assert payload["user"]["display_name"] == "Local Tester"


def test_telegram_redirect_callback_sets_cookie_and_returns_login_code(
    auth_client: TestClient,
) -> None:
    response = auth_client.get(
        "/api/v1/auth/telegram-callback",
        params=_telegram_payload(),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith("http://localhost:3000/auth/telegram?")
    assert "code=" in response.headers["location"]
    assert auth_client.cookies.get("refresh_token")


def test_telegram_login_code_exchange_returns_access_token(auth_client: TestClient) -> None:
    callback_response = auth_client.get(
        "/api/v1/auth/telegram-callback",
        params=_telegram_payload(),
        follow_redirects=False,
    )
    code = callback_response.headers["location"].split("code=", maxsplit=1)[1]

    response = auth_client.post(
        "/api/v1/auth/telegram-code",
        json={"code": code},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["telegram_id"] == "100500"


def test_telegram_login_code_exchange_rejects_reused_code(auth_client: TestClient) -> None:
    callback_response = auth_client.get(
        "/api/v1/auth/telegram-callback",
        params=_telegram_payload(),
        follow_redirects=False,
    )
    code = callback_response.headers["location"].split("code=", maxsplit=1)[1]

    first_response = auth_client.post("/api/v1/auth/telegram-code", json={"code": code})
    second_response = auth_client.post("/api/v1/auth/telegram-code", json={"code": code})

    assert first_response.status_code == 200
    assert second_response.status_code == 401
    assert second_response.json()["error"]["code"] == "invalid_telegram_login_code"


def test_telegram_redirect_callback_redirects_error_for_invalid_payload(
    auth_client: TestClient,
) -> None:
    payload = _telegram_payload()
    payload["hash"] = "invalid"

    response = auth_client.get(
        "/api/v1/auth/telegram-callback",
        params=payload,
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "http://localhost:3000/auth/telegram?error=invalid_telegram_login"
    )


def test_telegram_login_creates_user_and_sets_refresh_cookie(auth_client: TestClient) -> None:
    payload = _telegram_login(auth_client)

    assert payload["user"]["telegram_id"] == "100500"
    assert payload["user"]["telegram_username"] == "telegram_user"
    assert payload["user"]["display_name"] == "Telegram User"
    assert payload["access_token"]
    assert auth_client.cookies.get("refresh_token")


def test_telegram_login_updates_existing_user_profile(auth_client: TestClient) -> None:
    _telegram_login(auth_client)
    auth_client.cookies.clear()

    payload = _telegram_login(auth_client, first_name="Updated", last_name=None, username="updated")

    assert payload["user"]["telegram_id"] == "100500"
    assert payload["user"]["telegram_username"] == "updated"
    assert payload["user"]["display_name"] == "Updated"
    assert auth_client.cookies.get("refresh_token")


def test_telegram_login_rejects_invalid_hash(auth_client: TestClient) -> None:
    payload = _telegram_payload()
    payload["hash"] = "invalid"

    response = auth_client.post(
        "/api/v1/auth/telegram-login",
        json=payload,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_telegram_login"
    assert response.json()["error"]["message"] == "Invalid Telegram login data."


def test_telegram_login_rejects_expired_auth_date(auth_client: TestClient) -> None:
    auth_date = int((datetime.now(UTC) - timedelta(days=2)).timestamp())

    response = auth_client.post(
        "/api/v1/auth/telegram-login",
        json=_telegram_payload(auth_date=auth_date),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_telegram_login"
    assert response.json()["error"]["message"] == "Invalid Telegram login data."


def test_me_returns_current_user_for_valid_bearer_token(auth_client: TestClient) -> None:
    access_token = _telegram_login(auth_client)["access_token"]

    response = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["telegram_id"] == "100500"


def test_sessions_returns_active_sessions_for_current_user(auth_client: TestClient) -> None:
    _telegram_login(auth_client)
    auth_client.cookies.clear()
    access_token = _telegram_login(auth_client)["access_token"]

    response = auth_client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["is_current"] is True
    assert payload[0]["user_agent"] == "testclient"
    assert payload[0]["created_at"]
    assert payload[0]["expires_at"]
    assert payload[1]["is_current"] is False


def test_refresh_rotates_cookie_and_returns_new_access_token(auth_client: TestClient) -> None:
    _telegram_login(auth_client)
    first_refresh_token = auth_client.cookies.get("refresh_token")

    response = auth_client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert auth_client.cookies.get("refresh_token")
    assert auth_client.cookies.get("refresh_token") != first_refresh_token


def test_logout_revokes_session_and_clears_refresh_cookie(auth_client: TestClient) -> None:
    _telegram_login(auth_client)

    response = auth_client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert auth_client.cookies.get("refresh_token") is None

    refresh_response = auth_client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 401
    assert refresh_response.json()["error"]["code"] == "missing_refresh_token"
    assert refresh_response.json()["error"]["message"] == "Missing refresh token."


def test_logout_all_revokes_all_sessions(auth_client: TestClient) -> None:
    register_payload = _telegram_login(auth_client)
    _telegram_login(auth_client)

    response = auth_client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {register_payload['access_token']}"},
    )

    assert response.status_code == 204
    assert auth_client.cookies.get("refresh_token") is None

    me_response = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {register_payload['access_token']}"},
    )
    assert me_response.status_code == 401
    assert me_response.json()["error"]["code"] == "invalid_access_token"


def test_delete_specific_session_revokes_only_target_session(auth_client: TestClient) -> None:
    _telegram_login(auth_client)
    auth_client.cookies.clear()
    access_token = _telegram_login(auth_client)["access_token"]
    sessions_response = auth_client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    session_to_revoke = next(
        session for session in sessions_response.json() if not session["is_current"]
    )

    delete_response = auth_client.delete(
        f"/api/v1/auth/sessions/{session_to_revoke['id']}",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert delete_response.status_code == 204

    remaining_response = auth_client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    remaining_payload = remaining_response.json()
    assert len(remaining_payload) == 1
    assert remaining_payload[0]["is_current"] is True
