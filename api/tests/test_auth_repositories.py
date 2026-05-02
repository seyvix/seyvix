from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.modules.auth.infrastructure.repositories import AuthSessionRepository, UserRepository
from app.modules.auth.models import AuthSession, User


@pytest.mark.asyncio
async def test_user_repository_returns_user_by_telegram_id() -> None:
    session = AsyncMock()
    user = User(
        telegram_id="100500",
        display_name="User",
    )
    session.scalar.return_value = user

    repository = UserRepository(session)

    result = await repository.get_by_telegram_id("100500")

    assert result is user
    session.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_session_repository_lists_active_sessions_for_user() -> None:
    session = AsyncMock()
    auth_session = AuthSession(
        user=User(
            telegram_id="100500",
            display_name="User",
        ),
        refresh_token_hash="hash",
        expires_at=datetime.now(UTC),
    )
    session.scalars.return_value = [auth_session]

    repository = AuthSessionRepository(session)

    result = await repository.list_active_for_user("user-id")

    assert result == [auth_session]
    session.scalars.assert_awaited_once()
