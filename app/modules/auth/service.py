from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import AuthSession, User
from app.modules.auth.schemas import AuthSessionResponse, AuthTokensResponse, UserResponse
from app.modules.auth.security import (
    build_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expires_at,
    verify_password,
)


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


class InvalidAccessTokenError(Exception):
    pass


class SessionNotFoundError(Exception):
    pass


@dataclass(slots=True)
class AuthContext:
    user: User
    session: AuthSession


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[AuthTokensResponse, str]:
        existing_user = await self.session.scalar(select(User).where(User.email == email))
        if existing_user is not None:
            raise EmailAlreadyRegisteredError

        user = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
        )
        auth_response, refresh_token = await self._create_session_response(
            user=user,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return auth_response, refresh_token

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[AuthTokensResponse, str]:
        user = await self.session.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(password, user.password_hash) or not user.is_active:
            raise InvalidCredentialsError

        auth_response, refresh_token = await self._create_session_response(
            user=user,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return auth_response, refresh_token

    async def refresh(self, *, raw_refresh_token: str) -> tuple[AuthTokensResponse, str]:
        auth_session = await self._load_active_session(raw_refresh_token)
        user = auth_session.user
        if not user.is_active:
            raise InvalidRefreshTokenError

        new_refresh_token = generate_refresh_token()
        auth_session.expires_at = refresh_token_expires_at()
        auth_session.last_used_at = datetime.now(UTC)
        auth_session.refresh_token_hash = hash_refresh_token(new_refresh_token)
        await self.session.commit()
        await self.session.refresh(auth_session)

        return (
            AuthTokensResponse(
                user=UserResponse.model_validate(user, from_attributes=True),
                access_token=build_access_token(user_id=user.id, session_id=auth_session.id),
            ),
            new_refresh_token,
        )

    async def logout(self, *, raw_refresh_token: str | None) -> None:
        if not raw_refresh_token:
            return

        query = select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_refresh_token(raw_refresh_token),
            AuthSession.revoked_at.is_(None),
        )
        auth_session = await self.session.scalar(query)
        if auth_session is None:
            return

        auth_session.revoked_at = datetime.now(UTC)
        await self.session.commit()

    async def authenticate_access_token(self, access_token: str) -> UserResponse:
        context = await self.get_auth_context(access_token)
        return UserResponse.model_validate(context.user, from_attributes=True)

    async def get_auth_context(self, access_token: str) -> AuthContext:
        try:
            payload = decode_access_token(access_token)
        except Exception as exc:  # noqa: BLE001
            raise InvalidAccessTokenError from exc

        session_id = str(payload["sid"])
        user_id = str(payload["sub"])
        query = (
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(AuthSession.id == session_id, AuthSession.user_id == user_id)
        )
        auth_session = await self.session.scalar(query)
        if auth_session is None:
            raise InvalidAccessTokenError
        if auth_session.revoked_at is not None:
            raise InvalidAccessTokenError
        if self._normalize_datetime(auth_session.expires_at) <= datetime.now(UTC):
            raise InvalidAccessTokenError
        if not auth_session.user.is_active:
            raise InvalidAccessTokenError

        return AuthContext(user=auth_session.user, session=auth_session)

    async def list_sessions(
        self,
        *,
        user_id: str,
        current_session_id: str,
    ) -> list[AuthSessionResponse]:
        query = (
            select(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.created_at.desc())
        )
        sessions = list(await self.session.scalars(query))
        return [
            AuthSessionResponse(
                id=session.id,
                created_at=self._normalize_datetime(session.created_at).isoformat(),
                last_used_at=(
                    self._normalize_datetime(session.last_used_at).isoformat()
                    if session.last_used_at is not None
                    else None
                ),
                expires_at=self._normalize_datetime(session.expires_at).isoformat(),
                user_agent=session.user_agent,
                ip_address=session.ip_address,
                is_current=session.id == current_session_id,
            )
            for session in sessions
        ]

    async def logout_all(self, *, user_id: str) -> None:
        query = select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        sessions = list(await self.session.scalars(query))
        now = datetime.now(UTC)
        for session in sessions:
            session.revoked_at = now
        await self.session.commit()

    async def revoke_session(self, *, user_id: str, session_id: str) -> None:
        query = select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        auth_session = await self.session.scalar(query)
        if auth_session is None:
            raise SessionNotFoundError

        auth_session.revoked_at = datetime.now(UTC)
        await self.session.commit()

    async def _create_session_response(
        self,
        *,
        user: User,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[AuthTokensResponse, str]:
        raw_refresh_token = generate_refresh_token()
        auth_session = AuthSession(
            user=user,
            refresh_token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=refresh_token_expires_at(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.session.add_all([user, auth_session])
        await self.session.commit()
        await self.session.refresh(user)
        await self.session.refresh(auth_session)

        return (
            AuthTokensResponse(
                user=UserResponse.model_validate(user, from_attributes=True),
                access_token=build_access_token(user_id=user.id, session_id=auth_session.id),
            ),
            raw_refresh_token,
        )

    async def _load_active_session(self, raw_refresh_token: str) -> AuthSession:
        query = (
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(
                AuthSession.refresh_token_hash == hash_refresh_token(raw_refresh_token),
                AuthSession.revoked_at.is_(None),
            )
        )
        auth_session = await self.session.scalar(query)
        if auth_session is None:
            raise InvalidRefreshTokenError
        if self._normalize_datetime(auth_session.expires_at) <= datetime.now(UTC):
            raise InvalidRefreshTokenError
        return auth_session

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
