from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.auth.access import AccessDeniedError, AccessService
from app.modules.auth.infrastructure.repositories import AuthSessionRepository, UserRepository
from app.modules.auth.models import AuthSession, User
from app.modules.auth.schemas import (
    AuthSessionResponse,
    AuthTokensResponse,
    TelegramLoginRequest,
    UserResponse,
)
from app.modules.auth.security import (
    TelegramIdentity,
    build_access_token,
    decode_access_token,
    find_jwk,
    generate_token,
    hash_token,
    parse_telegram_web_app_init_data,
    unverified_kid,
    verify_telegram_login_data,
    verify_telegram_oidc_id_token,
)

logger = get_logger(__name__)

# A superseded refresh token presented within this window is a concurrent refresh from another
# tab (the browser already holds the new cookie); later it is treated as token theft.
REFRESH_REUSE_GRACE_SECONDS = 30
JWKS_CACHE_SECONDS = 3600


class AuthError(Exception):
    """Base class; the REST layer maps `status_code`/`code` to an error response."""

    status_code = 401
    code = "unauthorized"
    message = "Unauthorized."


class TelegramAuthNotConfiguredError(AuthError):
    status_code = 503
    code = "telegram_auth_not_configured"
    message = "Telegram authentication is not configured."


class TelegramDevLoginDisabledError(AuthError):
    status_code = 404
    code = "telegram_dev_login_disabled"
    message = "Telegram dev login is disabled."


class InvalidTelegramLoginError(AuthError):
    code = "invalid_telegram_login"
    message = "Invalid Telegram login data."


class InvalidTelegramWebAppLoginError(AuthError):
    code = "invalid_telegram_web_app_login"
    message = "Invalid Telegram Mini App login data."


class InvalidTelegramOidcLoginError(AuthError):
    code = "invalid_telegram_oidc_login"
    message = "Invalid Telegram OIDC login data."


class InvalidRefreshTokenError(AuthError):
    code = "invalid_refresh_token"
    message = "Invalid refresh token."


class InvalidAccessTokenError(AuthError):
    code = "invalid_access_token"
    message = "Invalid access token."


class AccountDisabledError(AuthError):
    status_code = 403
    code = "account_disabled"
    message = "This account is disabled."


class SessionNotFoundError(AuthError):
    status_code = 404
    code = "session_not_found"
    message = "Session not found."


@dataclass(slots=True)
class AuthContext:
    user: User
    session: AuthSession


_jwks_cache: tuple[float, dict[str, Any]] | None = None


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.auth_sessions = AuthSessionRepository(session)
        self.access = AccessService(session)

    # --- Identity verification (one method per login flow) --------------------------------

    @staticmethod
    def verify_widget_login(payload: TelegramLoginRequest) -> TelegramIdentity:
        settings = get_settings()
        if not settings.telegram_bot_token:
            raise TelegramAuthNotConfiguredError
        if not verify_telegram_login_data(
            payload.model_dump(exclude_none=True),
            bot_token=settings.telegram_bot_token,
            max_age_seconds=settings.telegram_login_max_age_seconds,
        ):
            raise InvalidTelegramLoginError
        return TelegramIdentity(
            telegram_id=payload.id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            username=payload.username,
            photo_url=payload.photo_url,
        )

    @staticmethod
    def verify_web_app_login(init_data: str) -> TelegramIdentity:
        settings = get_settings()
        if not settings.telegram_bot_token:
            raise TelegramAuthNotConfiguredError
        identity = parse_telegram_web_app_init_data(
            init_data,
            bot_token=settings.telegram_bot_token,
            max_age_seconds=settings.telegram_login_max_age_seconds,
        )
        if identity is None:
            raise InvalidTelegramWebAppLoginError
        return identity

    @staticmethod
    def dev_identity() -> TelegramIdentity:
        settings = get_settings()
        if not settings.telegram_dev_login_enabled or settings.is_production:
            raise TelegramDevLoginDisabledError
        return TelegramIdentity(
            telegram_id=settings.telegram_dev_user_id,
            first_name=settings.telegram_dev_first_name,
            last_name=settings.telegram_dev_last_name,
            username=settings.telegram_dev_username,
            photo_url=settings.telegram_dev_photo_url,
        )

    async def verify_oidc_login(self, *, code: str, code_verifier: str) -> TelegramIdentity:
        settings = get_settings()
        if not settings.telegram_oidc_client_id or not settings.telegram_oidc_client_secret:
            raise TelegramAuthNotConfiguredError
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(15.0, connect=10.0),
            "follow_redirects": False,
        }
        if settings.telegram_oidc_proxy_url:
            client_kwargs["proxy"] = settings.telegram_oidc_proxy_url
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                token_response = await client.post(
                    settings.telegram_oidc_token_url,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": settings.telegram_login_redirect_url,
                        "client_id": settings.telegram_oidc_client_id,
                        "code_verifier": code_verifier,
                    },
                    auth=httpx.BasicAuth(
                        settings.telegram_oidc_client_id,
                        settings.telegram_oidc_client_secret,
                    ),
                    headers={"Accept": "application/json"},
                )
                if token_response.status_code >= 400:
                    logger.warning(
                        "auth.oidc.token_exchange_failed",
                        status=token_response.status_code,
                    )
                    raise InvalidTelegramOidcLoginError
                token_payload = token_response.json()
                id_token = (
                    token_payload.get("id_token") if isinstance(token_payload, dict) else None
                )
                if not isinstance(id_token, str):
                    raise InvalidTelegramOidcLoginError
                jwks = await _telegram_jwks(client, kid=unverified_kid(id_token))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("auth.oidc.request_failed", error=type(exc).__name__)
            raise InvalidTelegramOidcLoginError from exc

        claims = verify_telegram_oidc_id_token(
            id_token,
            jwks=jwks,
            client_id=_telegram_oidc_audience(),
            issuer=settings.telegram_oidc_issuer,
        )
        if claims is None:
            raise InvalidTelegramOidcLoginError
        try:
            telegram_id = int(str(claims.get("id") or claims.get("sub")))
        except ValueError as exc:
            raise InvalidTelegramOidcLoginError from exc
        if telegram_id <= 0:
            raise InvalidTelegramOidcLoginError
        username = claims.get("preferred_username")
        picture = claims.get("picture")
        name = claims.get("name")
        return TelegramIdentity(
            telegram_id=telegram_id,
            first_name="",
            username=username if isinstance(username, str) and username else None,
            photo_url=picture if isinstance(picture, str) and picture else None,
            display_name=name if isinstance(name, str) else None,
        )

    # --- Sessions ---------------------------------------------------------------------------

    async def login(
        self,
        identity: TelegramIdentity,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[AuthTokensResponse, str]:
        """Check access, upsert the profile and start a session. Returns (tokens, refresh)."""
        await self.access.ensure_allowed(identity.telegram_id, identity.username)
        user = await self.users.upsert_active_telegram_profile(
            telegram_id=str(identity.telegram_id),
            display_name=identity.resolved_display_name(),
            telegram_username=identity.username,
            telegram_photo_url=identity.photo_url,
        )
        if user is None:
            await self.session.rollback()
            raise AccountDisabledError
        now = datetime.now(UTC)
        await self.auth_sessions.delete_dead_for_user(user_id=user.id, now=now)
        raw_refresh_token = generate_token()
        auth_session = AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_token(raw_refresh_token),
            created_at=now,
            expires_at=_session_expires_at(created_at=now, now=now),
            last_used_at=now,
            user_agent=user_agent[:512] if user_agent else None,
            ip_address=ip_address,
        )
        self.auth_sessions.add(auth_session)
        await self.session.commit()
        logger.info("auth.login", user_id=user.id, session_id=auth_session.id)
        return self._tokens(user, auth_session), raw_refresh_token

    async def refresh(self, *, raw_refresh_token: str) -> tuple[AuthTokensResponse, str | None]:
        """Rotate the refresh token. Returns (tokens, new refresh token or None).

        None means a concurrent refresh already rotated the token moments ago: the caller
        must keep the cookie the browser already received.
        """
        token_hash = hash_token(raw_refresh_token)
        auth_session = await self.auth_sessions.get_by_refresh_token_hash(
            token_hash,
            for_update=True,
        )
        now = datetime.now(UTC)
        if auth_session is None or not _is_live(auth_session, now):
            await self.session.rollback()
            raise InvalidRefreshTokenError
        user = auth_session.user
        if auth_session.refresh_token_hash != token_hash:
            if _within_reuse_grace(auth_session, now):
                tokens = self._tokens(user, auth_session)
                await self.session.commit()
                return tokens, None
            auth_session.revoked_at = now
            await self.session.commit()
            logger.warning(
                "auth.refresh_token_reuse_detected",
                user_id=user.id,
                session_id=auth_session.id,
            )
            raise InvalidRefreshTokenError
        if not user.is_active:
            await self.session.rollback()
            raise AccountDisabledError
        try:
            await self.access.ensure_allowed(
                int(user.telegram_id),
                user.telegram_username,
                record_login=False,
            )
        except AccessDeniedError:
            await self.auth_sessions.revoke_all_for_user(user_id=user.id, revoked_at=now)
            await self.session.commit()
            raise
        new_refresh_token = generate_token()
        auth_session.previous_refresh_token_hash = token_hash
        auth_session.refresh_token_hash = hash_token(new_refresh_token)
        auth_session.rotated_at = now
        auth_session.last_used_at = now
        auth_session.expires_at = _session_expires_at(created_at=auth_session.created_at, now=now)
        tokens = self._tokens(user, auth_session)
        await self.session.commit()
        return tokens, new_refresh_token

    async def logout(self, *, raw_refresh_token: str | None) -> None:
        if not raw_refresh_token:
            return
        auth_session = await self.auth_sessions.get_by_refresh_token_hash(
            hash_token(raw_refresh_token),
        )
        if auth_session is None or auth_session.revoked_at is not None:
            return
        auth_session.revoked_at = datetime.now(UTC)
        await self.session.commit()

    async def get_auth_context(self, access_token: str) -> AuthContext:
        decoded = decode_access_token(access_token)
        if decoded is None:
            raise InvalidAccessTokenError
        user_id, session_id = decoded
        auth_session = await self.auth_sessions.get_active_by_id_and_user_id(
            session_id=session_id,
            user_id=user_id,
            with_user=True,
        )
        if auth_session is None or not _is_live(auth_session, datetime.now(UTC)):
            raise InvalidAccessTokenError
        if not auth_session.user.is_active:
            raise InvalidAccessTokenError
        return AuthContext(user=auth_session.user, session=auth_session)

    async def get_auth_context_by_refresh_token(self, raw_refresh_token: str) -> AuthContext:
        """Cookie-based auth for resources loaded by the browser directly (images, media)."""
        token_hash = hash_token(raw_refresh_token)
        auth_session = await self.auth_sessions.get_by_refresh_token_hash(token_hash)
        now = datetime.now(UTC)
        if auth_session is None or not _is_live(auth_session, now):
            raise InvalidRefreshTokenError
        if auth_session.refresh_token_hash != token_hash and not _within_reuse_grace(
            auth_session, now
        ):
            raise InvalidRefreshTokenError
        if not auth_session.user.is_active:
            raise InvalidRefreshTokenError
        return AuthContext(user=auth_session.user, session=auth_session)

    async def list_sessions(
        self,
        *,
        user_id: str,
        current_session_id: str,
    ) -> list[AuthSessionResponse]:
        sessions = await self.auth_sessions.list_active_for_user(user_id, now=datetime.now(UTC))
        return [
            AuthSessionResponse(
                id=session.id,
                created_at=_aware(session.created_at).isoformat(),
                last_used_at=(
                    _aware(session.last_used_at).isoformat() if session.last_used_at else None
                ),
                expires_at=_aware(session.expires_at).isoformat(),
                user_agent=session.user_agent,
                ip_address=session.ip_address,
                is_current=session.id == current_session_id,
            )
            for session in sessions
        ]

    async def logout_all(self, *, user_id: str) -> None:
        await self.auth_sessions.revoke_all_for_user(user_id=user_id, revoked_at=datetime.now(UTC))
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

    @staticmethod
    def _tokens(user: User, auth_session: AuthSession) -> AuthTokensResponse:
        return AuthTokensResponse(
            user=UserResponse.model_validate(user, from_attributes=True),
            access_token=build_access_token(user_id=user.id, session_id=auth_session.id),
        )


async def _telegram_jwks(client: httpx.AsyncClient, *, kid: str | None) -> dict[str, Any]:
    """Telegram JWKS, cached; refetched when stale or when the token uses an unknown key."""
    global _jwks_cache
    cached = _jwks_cache
    if cached is not None and time.monotonic() - cached[0] < JWKS_CACHE_SECONDS:
        if kid is None or find_jwk(cached[1], kid) is not None:
            return cached[1]
    response = await client.get(get_settings().telegram_oidc_jwks_url)
    response.raise_for_status()
    jwks = response.json()
    if not isinstance(jwks, dict):
        raise ValueError("JWKS response is not an object")
    _jwks_cache = (time.monotonic(), jwks)
    return jwks


def _telegram_oidc_audience() -> str:
    settings = get_settings()
    if settings.telegram_oidc_client_id:
        return settings.telegram_oidc_client_id
    if settings.telegram_bot_token and ":" in settings.telegram_bot_token:
        return settings.telegram_bot_token.split(":", maxsplit=1)[0]
    raise TelegramAuthNotConfiguredError


def _session_expires_at(*, created_at: datetime, now: datetime) -> datetime:
    settings = get_settings()
    sliding = now + timedelta(days=settings.refresh_token_ttl_days)
    absolute = _aware(created_at) + timedelta(days=settings.refresh_token_absolute_ttl_days)
    return min(sliding, absolute)


def _is_live(auth_session: AuthSession, now: datetime) -> bool:
    return auth_session.revoked_at is None and _aware(auth_session.expires_at) > now


def _within_reuse_grace(auth_session: AuthSession, now: datetime) -> bool:
    rotated_at = auth_session.rotated_at
    if rotated_at is None:
        return False
    return now - _aware(rotated_at) <= timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
