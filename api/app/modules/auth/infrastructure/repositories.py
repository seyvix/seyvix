from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import AuthSession, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: str) -> User | None:
        query = select(User).where(User.telegram_id == telegram_id)
        return cast(User | None, await self.session.scalar(query))

    async def upsert_active_telegram_profile(
        self,
        *,
        telegram_id: str,
        display_name: str,
        telegram_username: str | None,
        telegram_photo_url: str | None,
    ) -> User | None:
        statement = (
            postgresql_insert(User)
            .values(
                telegram_id=telegram_id,
                display_name=display_name,
                telegram_username=telegram_username,
                telegram_photo_url=telegram_photo_url,
            )
            .on_conflict_do_update(
                index_elements=[User.telegram_id],
                set_={
                    "display_name": display_name,
                    "telegram_username": telegram_username,
                    "telegram_photo_url": telegram_photo_url,
                },
                where=User.is_active.is_(True),
            )
            .returning(User)
            .execution_options(populate_existing=True)
        )
        return cast(User | None, await self.session.scalar(statement))

    def add(self, user: User) -> None:
        self.session.add(user)


class AuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, auth_session: AuthSession) -> None:
        self.session.add(auth_session)

    async def get_active_by_refresh_token_hash(
        self,
        refresh_token_hash: str,
        *,
        with_user: bool = False,
    ) -> AuthSession | None:
        query = select(AuthSession).where(
            AuthSession.refresh_token_hash == refresh_token_hash,
            AuthSession.revoked_at.is_(None),
        )
        if with_user:
            query = query.options(selectinload(AuthSession.user))
        return cast(AuthSession | None, await self.session.scalar(query))

    async def get_active_by_id_and_user_id(
        self,
        *,
        session_id: str,
        user_id: str,
        with_user: bool = False,
    ) -> AuthSession | None:
        query = select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        if with_user:
            query = query.options(selectinload(AuthSession.user))
        return cast(AuthSession | None, await self.session.scalar(query))

    async def get_active_by_login_code_hash(
        self,
        login_code_hash: str,
        *,
        with_user: bool = False,
    ) -> AuthSession | None:
        query = select(AuthSession).where(
            AuthSession.login_code_hash == login_code_hash,
            AuthSession.revoked_at.is_(None),
        )
        if with_user:
            query = query.options(selectinload(AuthSession.user))
        return cast(AuthSession | None, await self.session.scalar(query))

    async def list_active_for_user(self, user_id: str) -> list[AuthSession]:
        query = (
            select(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.created_at.desc())
        )
        return list(await self.session.scalars(query))

    async def revoke_all_for_user(self, *, user_id: str, revoked_at: datetime) -> list[AuthSession]:
        sessions = await self.list_active_for_user(user_id)
        for session in sessions:
            session.revoked_at = revoked_at
        return sessions
