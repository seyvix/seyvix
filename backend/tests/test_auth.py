import asyncio
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, build_session_factory
from app.main import app
from app.modules.auth.presentation.rest import router as auth_router
from app.modules.auth.schemas import TelegramLoginRequest
from app.modules.auth.service import AuthService

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


async def _prepare_database(database_url: str) -> async_sessionmaker:
    engine: AsyncEngine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return build_session_factory(database_url)


def _test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database for DB-resetting tests.")
    return database_url


@pytest.fixture
def auth_client() -> TestClient:
    os.environ["TELEGRAM_BOT_TOKEN"] = TELEGRAM_BOT_TOKEN
    os.environ["TELEGRAM_LOGIN_REDIRECT_URL"] = "http://localhost:3000/auth/callback"
    os.environ["TELEGRAM_DEV_LOGIN_ENABLED"] = "false"
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


def _telegram_web_app_init_data(
    *,
    telegram_id: int = 100500,
    first_name: str = "Telegram",
    last_name: str | None = "User",
    username: str | None = "telegram_user",
    photo_url: str | None = "https://t.me/i/userpic/320/example.jpg",
    auth_date: int | None = None,
) -> str:
    user: dict[str, object] = {
        "id": telegram_id,
        "first_name": first_name,
    }
    if last_name is not None:
        user["last_name"] = last_name
    if username is not None:
        user["username"] = username
    if photo_url is not None:
        user["photo_url"] = photo_url

    payload: dict[str, str] = {
        "query_id": "AAEAAAE",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        "auth_date": str(auth_date or int(datetime.now(UTC).timestamp())),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hmac.new(
        b"WebAppData",
        TELEGRAM_BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    payload["hash"] = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(payload)


def _telegram_login(auth_client: TestClient, **payload_overrides: object) -> dict[str, object]:
    response = auth_client.post(
        "/api/v1/auth/telegram-login",
        json=_telegram_payload(**payload_overrides),
    )
    assert response.status_code == 200
    return response.json()


def test_telegram_web_app_login_creates_user_and_sets_refresh_cookie(
    auth_client: TestClient,
) -> None:
    response = auth_client.post(
        "/api/v1/auth/telegram-web-app",
        json={"init_data": _telegram_web_app_init_data()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["telegram_id"] == "100500"
    assert payload["user"]["telegram_username"] == "telegram_user"
    assert payload["user"]["display_name"] == "Telegram User"
    assert auth_client.cookies.get("refresh_token")


def test_telegram_web_app_login_rejects_invalid_hash(auth_client: TestClient) -> None:
    init_data = _telegram_web_app_init_data().replace("hash=", "hash=invalid")

    response = auth_client.post(
        "/api/v1/auth/telegram-web-app",
        json={"init_data": init_data},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_telegram_web_app_login"


def test_telegram_web_app_login_rejects_expired_auth_date(auth_client: TestClient) -> None:
    auth_date = int((datetime.now(UTC) - timedelta(days=2)).timestamp())

    response = auth_client.post(
        "/api/v1/auth/telegram-web-app",
        json={"init_data": _telegram_web_app_init_data(auth_date=auth_date)},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_telegram_web_app_login"


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
    assert response.headers["location"].startswith("http://localhost:3000/auth/callback?")
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
    assert response.headers["location"].startswith("http://localhost:3000/auth/callback?")
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
        "http://localhost:3000/auth/callback?error=invalid_telegram_login"
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


def test_concurrent_telegram_logins_for_new_user_are_idempotent(
    auth_client: TestClient,
) -> None:
    async def login_once() -> dict[str, object]:
        async with app.state.session_factory() as session:
            service = AuthService(session)
            auth_response, _ = await service.telegram_login(
                payload=TelegramLoginRequest(**_telegram_payload()),
                user_agent="testclient",
                ip_address="127.0.0.1",
            )
            return auth_response.model_dump()

    async def login_twice() -> list[dict[str, object]]:
        first, second = await asyncio.gather(login_once(), login_once())
        return [first, second]

    results = asyncio.run(login_twice())

    assert [result["user"]["telegram_id"] for result in results] == ["100500", "100500"]
    assert all(result["access_token"] for result in results)


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
    assert response.json()["avatar_url"] == "/api/v1/auth/me/avatar"


def test_current_user_avatar_proxies_telegram_photo(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str):
            requested_urls.append(url)

            class FakeResponse:
                content = b"avatar-bytes"
                headers = {"content-type": "image/jpeg"}

                def raise_for_status(self) -> None:
                    return None

            return FakeResponse()

    monkeypatch.setattr(auth_router.httpx, "AsyncClient", FakeAsyncClient)
    _telegram_login(auth_client, photo_url="https://t.me/i/userpic/320/example.jpg")

    response = auth_client.get("/api/v1/auth/me/avatar")

    assert response.status_code == 200
    assert response.content == b"avatar-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert requested_urls == ["https://t.me/i/userpic/320/example.jpg"]


def test_current_user_avatar_falls_back_to_bot_profile_photo(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[tuple[str, object | None]] = []

    class FakeAsyncClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object):
            requested.append((url, kwargs.get("params")))

            class FakeResponse:
                headers = {"content-type": "image/jpeg"}

                @property
                def content(self) -> bytes:
                    return b"avatar-from-bot-api"

                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict[str, object]:
                    if url.endswith("/getUserProfilePhotos"):
                        return {
                            "ok": True,
                            "result": {
                                "photos": [
                                    [
                                        {
                                            "file_id": "small-photo",
                                            "width": 80,
                                            "height": 80,
                                        },
                                        {
                                            "file_id": "large-photo",
                                            "width": 320,
                                            "height": 320,
                                        },
                                    ]
                                ]
                            },
                        }
                    if url.endswith("/getFile"):
                        return {
                            "ok": True,
                            "result": {"file_path": "photos/current-avatar.jpg"},
                        }
                    return {}

            return FakeResponse()

    monkeypatch.setattr(auth_router.httpx, "AsyncClient", FakeAsyncClient)
    _telegram_login(auth_client, photo_url=None)

    response = auth_client.get("/api/v1/auth/me/avatar")

    assert response.status_code == 200
    assert response.content == b"avatar-from-bot-api"
    assert response.headers["content-type"] == "image/jpeg"
    assert requested == [
        (
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUserProfilePhotos",
            {"user_id": "100500", "limit": 1},
        ),
        (
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
            {"file_id": "large-photo"},
        ),
        (
            f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/photos/current-avatar.jpg",
            None,
        ),
    ]


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
