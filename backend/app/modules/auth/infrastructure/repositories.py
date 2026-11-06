from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.auth.models import AuthSession, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: str) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(select(User).where(User.telegram_id == telegram_id)),
        )

    async def upsert_active_telegram_profile(
        self,
        *,
        telegram_id: str,
        display_name: str,
        telegram_username: str | None,
        telegram_photo_url: str | None,
    ) -> User | None:
        """Insert or refresh the profile; returns None for a deactivated account."""
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


class AuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, auth_session: AuthSession) -> None:
        self.session.add(auth_session)

    async def get_by_refresh_token_hash(
        self,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> AuthSession | None:
        """Session whose current *or* superseded refresh token has this hash (user loaded)."""
        query = (
            select(AuthSession)
            .options(joinedload(AuthSession.user, innerjoin=True))
            .where(
                or_(
                    AuthSession.refresh_token_hash == token_hash,
                    AuthSession.previous_refresh_token_hash == token_hash,
                )
            )
            .limit(1)
        )
        if for_update:
            query = query.with_for_update(of=AuthSession)
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
            query = query.options(joinedload(AuthSession.user, innerjoin=True))
        return cast(AuthSession | None, await self.session.scalar(query))

    async def list_active_for_user(self, user_id: str, *, now: datetime) -> list[AuthSession]:
        query = (
            select(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .order_by(AuthSession.created_at.desc())
        )
        return list(await self.session.scalars(query))

    async def revoke_all_for_user(self, *, user_id: str, revoked_at: datetime) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )

    async def delete_dead_for_user(self, *, user_id: str, now: datetime) -> None:
        """Prune the user's expired/revoked sessions so the table does not grow forever."""
        await self.session.execute(
            delete(AuthSession).where(
                AuthSession.user_id == user_id,
                or_(AuthSession.revoked_at.is_not(None), AuthSession.expires_at <= now),
            )
        )
