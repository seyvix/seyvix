"""Auth + access-control integration tests (need TEST_DATABASE_URL)."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import get_settings
from app.main import app
from app.modules.auth.models import AuthSession
from tests.conftest import prepare_database, require_database_url

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"
ADMIN_ID = 100500
DEV_ID = 777001
AUTH_ENV = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_INTERNAL_TOKEN": "internal-token-for-tests-0123456789abcdef",
    "PUBLIC_URL": "http://localhost:8080",
    "ACCESS_MODE": "allowlist",
    "ADMIN_TELEGRAM_IDS": f"{ADMIN_ID},{DEV_ID}",
    "TELEGRAM_DEV_LOGIN_ENABLED": "false",
}


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for key, value in AUTH_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    database_url = require_database_url()
    try:
        app.state.session_factory = asyncio.run(prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for auth tests: {exc}")
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def set_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def widget_payload(
    *,
    telegram_id: int = ADMIN_ID,
    first_name: str = "Telegram",
    username: str | None = "telegram_user",
    auth_date: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": telegram_id,
        "first_name": first_name,
        "auth_date": auth_date or int(datetime.now(UTC).timestamp()),
    }
    if username is not None:
        payload["username"] = username
    check = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return payload


def web_app_init_data(*, telegram_id: int = ADMIN_ID, username: str = "telegram_user") -> str:
    user = {"id": telegram_id, "first_name": "Telegram", "last_name": "User", "username": username}
    payload = {
        "query_id": "AAEAAAE",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(datetime.now(UTC).timestamp())),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


def login(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.post("/api/v1/auth/telegram-login", json=widget_payload(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


def bearer(tokens: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def run_db(statement: object) -> None:
    async def execute() -> None:
        async with app.state.session_factory() as session:
            await session.execute(statement)
            await session.commit()

    asyncio.run(execute())


def test_web_app_login_for_admin_sets_scoped_refresh_cookie(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/auth/telegram-web-app",
        json={"init_data": web_app_init_data()},
    )

    assert response.status_code == 200, response.text
    user = response.json()["user"]
    assert user["telegram_id"] == str(ADMIN_ID)
    assert user["display_name"] == "Telegram User"
    assert user["is_admin"] is True
    cookie = response.headers["set-cookie"]
    assert "refresh_token=" in cookie and "Path=/api/v1" in cookie and "HttpOnly" in cookie


def test_login_of_unlisted_user_is_denied_with_telegram_id(auth_client: TestClient) -> None:
    for response in (
        auth_client.post("/api/v1/auth/telegram-login", json=widget_payload(telegram_id=555)),
        auth_client.post(
            "/api/v1/auth/telegram-web-app",
            json={"init_data": web_app_init_data(telegram_id=555)},
        ),
    ):
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "access_denied"
        assert error["details"][0]["telegram_user_id"] == 555
    assert "refresh_token" not in auth_client.cookies


def test_invalid_signature_is_rejected(auth_client: TestClient) -> None:
    payload = widget_payload()
    payload["hash"] = "0" * 64
    response = auth_client.post("/api/v1/auth/telegram-login", json=payload)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_telegram_login"


def test_open_mode_lets_anyone_in(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, ACCESS_MODE="open")
    tokens = login(auth_client, telegram_id=555, username="anyone")
    assert tokens["user"]["is_admin"] is False


def test_admin_grants_username_which_binds_on_first_login(auth_client: TestClient) -> None:
    admin = login(auth_client)
    created = auth_client.post(
        "/api/v1/admin/access",
        headers=bearer(admin),
        json={"username": "@Friend_Name", "note": "college"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["username"] == "friend_name"
    duplicate = auth_client.post(
        "/api/v1/admin/access", headers=bearer(admin), json={"username": "friend_name"}
    )
    assert duplicate.status_code == 409

    auth_client.cookies.clear()
    friend = login(auth_client, telegram_id=4242, username="friend_name", first_name="Friend")
    assert friend["user"]["is_admin"] is False
    me = auth_client.get("/api/v1/auth/me", headers=bearer(friend))
    assert me.json()["is_admin"] is False

    listing = auth_client.get("/api/v1/admin/access", headers=bearer(admin)).json()
    assert listing["mode"] == "allowlist"
    assert listing["admins"] == [ADMIN_ID, DEV_ID]
    item = listing["items"][0]
    assert item["telegram_user_id"] == 4242
    assert item["display_name"] == "Friend"
    assert item["last_login_at"] is not None


def test_admin_api_requires_admin(auth_client: TestClient) -> None:
    admin = login(auth_client)
    auth_client.post("/api/v1/admin/access", headers=bearer(admin), json={"telegram_user_id": 7})
    auth_client.cookies.clear()
    user = login(auth_client, telegram_id=7, username=None)

    assert auth_client.get("/api/v1/admin/access", headers=bearer(user)).status_code == 403
    assert auth_client.get("/api/v1/admin/access").status_code == 401
    invalid = auth_client.post("/api/v1/admin/access", headers=bearer(admin), json={})
    assert invalid.status_code == 422


def test_revoking_access_kills_sessions(auth_client: TestClient) -> None:
    admin = login(auth_client)
    grant = auth_client.post(
        "/api/v1/admin/access", headers=bearer(admin), json={"telegram_user_id": 9}
    ).json()
    auth_client.cookies.clear()
    user = login(auth_client, telegram_id=9, username=None)
    user_cookie = auth_client.cookies.get("refresh_token")

    deleted = auth_client.delete(f"/api/v1/admin/access/{grant['id']}", headers=bearer(admin))
    assert deleted.status_code == 204
    assert (
        auth_client.delete(f"/api/v1/admin/access/{grant['id']}", headers=bearer(admin)).status_code
        == 404
    )

    assert auth_client.get("/api/v1/auth/me", headers=bearer(user)).status_code == 401
    auth_client.cookies.set("refresh_token", user_cookie, path="/api/v1")
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401
    retry = auth_client.post("/api/v1/auth/telegram-login", json=widget_payload(telegram_id=9))
    assert retry.status_code == 403


def test_refresh_is_denied_when_access_was_withdrawn(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_env(monkeypatch, ACCESS_MODE="open")
    login(auth_client, telegram_id=31, username=None)
    set_env(monkeypatch, ACCESS_MODE="allowlist")

    response = auth_client.post("/api/v1/auth/refresh")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "access_denied"


def test_refresh_rotates_and_detects_reuse(auth_client: TestClient) -> None:
    login(auth_client)
    original = auth_client.cookies.get("refresh_token")

    rotated = auth_client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    new_cookie = auth_client.cookies.get("refresh_token")
    assert new_cookie and new_cookie != original

    # A concurrent refresh with the superseded token (another tab) still succeeds…
    auth_client.cookies.set("refresh_token", original, path="/api/v1")
    concurrent = auth_client.post("/api/v1/auth/refresh")
    assert concurrent.status_code == 200
    assert "set-cookie" not in concurrent.headers

    # …but a replay after the grace window is treated as theft and kills the session.
    run_db(update(AuthSession).values(rotated_at=datetime.now(UTC) - timedelta(minutes=5)))
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401
    auth_client.cookies.set("refresh_token", new_cookie, path="/api/v1")
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401


def test_sessions_list_and_logout_all(auth_client: TestClient) -> None:
    first = login(auth_client)
    login(auth_client)

    sessions = auth_client.get("/api/v1/auth/sessions", headers=bearer(first)).json()
    assert len(sessions) == 2
    assert sum(1 for session in sessions if session["is_current"]) == 1

    assert auth_client.post("/api/v1/auth/logout-all", headers=bearer(first)).status_code == 204
    assert auth_client.get("/api/v1/auth/me", headers=bearer(first)).status_code == 401


def test_logout_revokes_session_and_clears_cookie(auth_client: TestClient) -> None:
    tokens = login(auth_client)
    assert auth_client.post("/api/v1/auth/logout").status_code == 204
    assert auth_client.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 401


def test_widget_redirect_forwards_to_spa_without_creating_a_session(
    auth_client: TestClient,
) -> None:
    payload = widget_payload()
    response = auth_client.get(
        "/api/v1/auth/telegram-callback",
        params={key: str(value) for key, value in payload.items()},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "set-cookie" not in response.headers
    location = urlsplit(response.headers["location"])
    assert location.path == "/auth/callback"
    tg_auth_result = parse_qs(location.fragment)["tgAuthResult"][0]

    exchanged = auth_client.post(
        "/api/v1/auth/telegram-result",
        json={"tg_auth_result": tg_auth_result},
    )
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["user"]["telegram_id"] == str(ADMIN_ID)


def test_dev_login_is_disabled_by_default(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/auth/telegram-dev-login", follow_redirects=False)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "telegram_dev_login_disabled"


def test_dev_login_code_is_bound_to_the_browser(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_env(monkeypatch, TELEGRAM_DEV_LOGIN_ENABLED="true", TELEGRAM_DEV_USER_ID=str(DEV_ID))
    redirect = auth_client.get("/api/v1/auth/telegram-dev-login", follow_redirects=False)
    assert redirect.status_code == 302
    assert "refresh_token" not in auth_client.cookies
    code = parse_qs(urlsplit(redirect.headers["location"]).query)["code"][0]

    # A code from a link without the matching state cookie (login CSRF) is rejected.
    state_cookie = auth_client.cookies.get("telegram_login_state")
    auth_client.cookies.delete("telegram_login_state", path="/api/v1/auth")
    forged = auth_client.post("/api/v1/auth/telegram-code", json={"code": code})
    assert forged.status_code == 401

    auth_client.cookies.set("telegram_login_state", state_cookie, path="/api/v1/auth")
    exchanged = auth_client.post("/api/v1/auth/telegram-code", json={"code": code})
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["user"]["telegram_id"] == str(DEV_ID)
    assert auth_client.cookies.get("refresh_token")


def test_oidc_code_exchange_requires_matching_state(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/auth/telegram-oidc-code",
        json={"code": "abc", "state": "unknown"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_telegram_oidc_state"


def test_bootstrap_endpoint_is_gone(auth_client: TestClient) -> None:
    assert auth_client.get("/api/v1/auth/bootstrap").status_code in {404, 405}
