import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database import Base, build_session_factory
from app.main import app


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
    database_url = _test_database_url()
    try:
        app.state.session_factory = asyncio.run(_prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for auth tests: {exc}")

    with TestClient(app) as client:
        yield client


def _register(auth_client: TestClient) -> dict[str, object]:
    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "display_name": "User",
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_register_creates_user_and_sets_refresh_cookie(auth_client: TestClient) -> None:
    payload = _register(auth_client)

    assert payload["user"]["email"] == "user@example.com"
    assert payload["access_token"]
    assert auth_client.cookies.get("refresh_token")


def test_register_rejects_duplicate_email(auth_client: TestClient) -> None:
    _register(auth_client)

    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "display_name": "Duplicate",
            "password": "StrongPass123!",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"
    assert response.json()["error"]["message"] == "Email already registered."


def test_login_returns_access_token_and_sets_refresh_cookie(auth_client: TestClient) -> None:
    _register(auth_client)
    auth_client.cookies.clear()

    response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "StrongPass123!"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert auth_client.cookies.get("refresh_token")


def test_me_returns_current_user_for_valid_bearer_token(auth_client: TestClient) -> None:
    access_token = _register(auth_client)["access_token"]

    response = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


def test_sessions_returns_active_sessions_for_current_user(auth_client: TestClient) -> None:
    _register(auth_client)
    login_response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "StrongPass123!"},
    )
    access_token = login_response.json()["access_token"]

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
    _register(auth_client)
    first_refresh_token = auth_client.cookies.get("refresh_token")

    response = auth_client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert auth_client.cookies.get("refresh_token")
    assert auth_client.cookies.get("refresh_token") != first_refresh_token


def test_logout_revokes_session_and_clears_refresh_cookie(auth_client: TestClient) -> None:
    _register(auth_client)

    response = auth_client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert auth_client.cookies.get("refresh_token") is None

    refresh_response = auth_client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 401
    assert refresh_response.json()["error"]["code"] == "missing_refresh_token"
    assert refresh_response.json()["error"]["message"] == "Missing refresh token."


def test_logout_all_revokes_all_sessions(auth_client: TestClient) -> None:
    register_payload = _register(auth_client)
    auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "StrongPass123!"},
    )

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
    _register(auth_client)
    login_response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "StrongPass123!"},
    )
    access_token = login_response.json()["access_token"]
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


def test_login_rejects_invalid_credentials(auth_client: TestClient) -> None:
    _register(auth_client)

    response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "WrongPass123!"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.json()["error"]["message"] == "Invalid credentials."
