"""FastAPI dependencies other modules use to authenticate requests."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.core.config import get_settings
from app.modules.auth.access import is_admin_telegram_id
from app.modules.auth.service import AuthContext, AuthError, AuthService

bearer_auth_scheme = HTTPBearer(scheme_name="BearerAuth", auto_error=False)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthService:
    return AuthService(session)


def auth_app_error(exc: AuthError) -> AppError:
    return AppError(status_code=exc.status_code, code=exc.code, message=exc.message)


def _missing_token() -> AppError:
    return AppError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="missing_access_token",
        message="Missing access token.",
    )


async def get_auth_context(
    service: Annotated[AuthService, Depends(get_auth_service)],
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_auth_scheme),
    ] = None,
) -> AuthContext:
    if not authorization or not authorization.credentials:
        raise _missing_token()
    try:
        return await service.get_auth_context(authorization.credentials.strip())
    except AuthError as exc:
        raise auth_app_error(exc) from exc


async def get_auth_context_from_bearer_or_refresh_cookie(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_auth_scheme),
    ] = None,
) -> AuthContext:
    """For URLs the browser loads directly (img/video src) where no bearer header is sent."""
    if authorization and authorization.credentials:
        try:
            return await service.get_auth_context(authorization.credentials.strip())
        except AuthError as exc:
            raise auth_app_error(exc) from exc
    raw_refresh_token = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw_refresh_token:
        raise _missing_token()
    try:
        return await service.get_auth_context_by_refresh_token(raw_refresh_token)
    except AuthError as exc:
        raise auth_app_error(exc) from exc


async def require_admin(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    """Authenticated admin (Telegram id listed in ADMIN_TELEGRAM_IDS); 403 otherwise."""
    if not is_admin_telegram_id(context.user.telegram_id):
        raise AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="admin_required",
            message="Administrator access is required.",
        )
    return context
