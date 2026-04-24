from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.infrastructure.repositories import AuthSessionRepository, UserRepository
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
        self.users = UserRepository(session)
        self.auth_sessions = AuthSessionRepository(session)

    async def register(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[AuthTokensResponse, str]:
        existing_user = await self.users.get_by_email(email)
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
        user = await self.users.get_by_email(email)
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

        auth_session = await self.auth_sessions.get_active_by_refresh_token_hash(
            hash_refresh_token(raw_refresh_token),
        )
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
        auth_session = await self.auth_sessions.get_active_by_id_and_user_id(
            session_id=session_id,
            user_id=user_id,
            with_user=True,
        )
        if auth_session is None:
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
        sessions = await self.auth_sessions.list_active_for_user(user_id)
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
        now = datetime.now(UTC)
        await self.auth_sessions.revoke_all_for_user(user_id=user_id, revoked_at=now)
        await self.session.commit()

    async def revoke_session(self, *, user_id: str, session_id: str) -> None:
        auth_session = await self.auth_sessions.get_active_by_id_and_user_id(
            session_id=session_id,
            user_id=user_id,
        )
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
        self.users.add(user)
        self.auth_sessions.add(auth_session)
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
        auth_session = await self.auth_sessions.get_active_by_refresh_token_hash(
            hash_refresh_token(raw_refresh_token),
            with_user=True,
        )
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
