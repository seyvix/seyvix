import base64
import json
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Query, Request, Response, Security, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.core.config import get_settings
from app.modules.auth.schemas import (
    AuthSessionResponse,
    AuthTokensResponse,
    TelegramAuthResultRequest,
    TelegramLoginCodeExchangeRequest,
    TelegramLoginRequest,
    UserResponse,
)
from app.modules.auth.service import (
    AuthContext,
    AuthService,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
    InvalidTelegramLoginCodeError,
    InvalidTelegramLoginError,
    SessionNotFoundError,
    TelegramAuthNotConfiguredError,
    TelegramDevLoginDisabledError,
)

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_auth_scheme = HTTPBearer(scheme_name="BearerAuth", auto_error=False)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthService:
    return AuthService(session)


async def get_auth_context(
    service: Annotated[AuthService, Depends(get_auth_service)],
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_auth_scheme),
    ] = None,
) -> AuthContext:
    if not authorization or not authorization.credentials:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="missing_access_token",
            message="Missing access token.",
        )

    access_token = authorization.credentials.strip()
    try:
        return await service.get_auth_context(access_token)
    except InvalidAccessTokenError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_access_token",
            message="Invalid access token.",
        ) from exc


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=f"{settings.api_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=f"{settings.api_prefix}/auth",
    )


def _build_telegram_redirect_url(**params: str) -> str:
    settings = get_settings()
    if settings.telegram_login_redirect_url is None:
        raise TelegramAuthNotConfiguredError

    parts = urlsplit(settings.telegram_login_redirect_url)
    query = dict(parse_qsl(parts.query))
    query.update(params)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        ),
    )


@router.get(
    "/telegram-login",
    include_in_schema=False,
    summary="Initiate Telegram login",
)
async def telegram_login_redirect(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> RedirectResponse:
    """
    Единая точка входа для авторизации через Telegram.
    В dev-режиме делегирует в telegram-dev-login.
    В prod-режиме строит редирект на oauth.telegram.org.
    """
    settings = get_settings()

    if settings.telegram_dev_login_enabled:
        try:
            login_code, refresh_token = await service.telegram_dev_redirect_login(
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
            )
        except TelegramDevLoginDisabledError as exc:
            raise AppError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="telegram_dev_login_disabled",
                message="Telegram dev login is disabled.",
            ) from exc
        except TelegramAuthNotConfiguredError as exc:
            raise AppError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="telegram_auth_not_configured",
                message="Telegram authentication is not configured.",
            ) from exc

        response = RedirectResponse(_build_telegram_redirect_url(code=login_code))
        _set_refresh_cookie(response, refresh_token)
        return response

    if not settings.telegram_bot_token:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="telegram_auth_not_configured",
            message="Telegram authentication is not configured.",
        )
    if not settings.telegram_login_redirect_url:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="telegram_auth_not_configured",
            message="Telegram login redirect URL is not configured.",
        )

    bot_id = settings.telegram_bot_token.split(":")[0]

    # Берём origin фронтенда из TELEGRAM_LOGIN_REDIRECT_URL
    redirect_parts = urlsplit(settings.telegram_login_redirect_url)
    frontend_origin = f"{redirect_parts.scheme}://{redirect_parts.netloc}"

    # Telegram appends #tgAuthResult=... as fragment — frontend reads it and calls /telegram-result
    return_to = f"{frontend_origin}/auth/callback"

    params = urlencode({"bot_id": bot_id, "origin": frontend_origin, "return_to": return_to})
    return RedirectResponse(f"https://oauth.telegram.org/auth?{params}")


@router.get(
    "/telegram-dev-login",
    include_in_schema=False,
)
async def telegram_dev_login(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> RedirectResponse:
    try:
        login_code, refresh_token = await service.telegram_dev_redirect_login(
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except TelegramDevLoginDisabledError as exc:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="telegram_dev_login_disabled",
            message="Telegram dev login is disabled.",
        ) from exc
    except TelegramAuthNotConfiguredError as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="telegram_auth_not_configured",
            message="Telegram authentication is not configured.",
        ) from exc

    response = RedirectResponse(_build_telegram_redirect_url(code=login_code))
    _set_refresh_cookie(response, refresh_token)
    return response


@router.get(
    "/telegram-callback",
    summary="Telegram redirect callback",
    description=(
        "Receives Telegram Login Widget redirect data, verifies it, starts a session, "
        "sets the refresh cookie, and redirects to the frontend with a one-time login code. "
        "Accepts either tgAuthResult (base64 JSON from oauth.telegram.org) or individual query params."
    ),
    responses={
        307: {"description": "Redirects to the configured frontend Telegram callback URL."},
        503: {"model": ErrorResponse, "description": "Telegram authentication is not configured."},
    },
)
async def telegram_callback(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    tg_auth_result: Annotated[str | None, Query(alias="tgAuthResult")] = None,
    telegram_id: Annotated[int | None, Query(alias="id", gt=0)] = None,
    first_name: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    auth_date: Annotated[int | None, Query(gt=0)] = None,
    telegram_hash: Annotated[str | None, Query(alias="hash")] = None,
    last_name: Annotated[str | None, Query(max_length=255)] = None,
    username: Annotated[str | None, Query(max_length=255)] = None,
    photo_url: Annotated[str | None, Query(max_length=2048)] = None,
) -> RedirectResponse:
    # Only handles the Login Widget individual-param redirect (not oauth.telegram.org flow).
    # The oauth.telegram.org flow sends #tgAuthResult in fragment — handled on the frontend
    # via POST /telegram-result.
    if telegram_id and first_name and auth_date and telegram_hash:
        payload = TelegramLoginRequest(
            id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            photo_url=photo_url,
            auth_date=auth_date,
            hash=telegram_hash,
        )
        try:
            login_code, refresh_token = await service.telegram_redirect_login(
                payload=payload,
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
            )
        except InvalidTelegramLoginError:
            return RedirectResponse(_build_telegram_redirect_url(error="invalid_telegram_login"))
        except TelegramAuthNotConfiguredError as exc:
            raise AppError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="telegram_auth_not_configured",
                message="Telegram authentication is not configured.",
            ) from exc

        response = RedirectResponse(_build_telegram_redirect_url(code=login_code))
        _set_refresh_cookie(response, refresh_token)
        return response

    return RedirectResponse(_build_telegram_redirect_url(error="invalid_telegram_login"))


@router.post(
    "/telegram-login",
    response_model=AuthTokensResponse,
    summary="Login with Telegram",
    description=(
        "Verifies Telegram Login Widget data, creates or updates the user profile, "
        "starts an authenticated session, returns an access token, and sets a refresh token "
        "in an httpOnly cookie."
    ),
    responses={
        200: {"description": "User authenticated with Telegram."},
        401: {"model": ErrorResponse, "description": "Invalid Telegram login data."},
        503: {"model": ErrorResponse, "description": "Telegram authentication is not configured."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
    },
)
async def telegram_login(
    payload: TelegramLoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokensResponse:
    try:
        auth_response, refresh_token = await service.telegram_login(
            payload=payload,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except InvalidTelegramLoginError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_login",
            message="Invalid Telegram login data.",
        ) from exc
    except TelegramAuthNotConfiguredError as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="telegram_auth_not_configured",
            message="Telegram authentication is not configured.",
        ) from exc

    _set_refresh_cookie(response, refresh_token)
    return auth_response


@router.post(
    "/telegram-result",
    response_model=AuthTokensResponse,
    summary="Exchange tgAuthResult from oauth.telegram.org",
    description=(
        "Decodes the base64url tgAuthResult fragment set by oauth.telegram.org, verifies the "
        "Telegram signature, creates or updates the user, starts a session, and returns tokens."
    ),
    responses={
        200: {"description": "User authenticated."},
        401: {"model": ErrorResponse, "description": "Invalid or expired Telegram auth result."},
        503: {"model": ErrorResponse, "description": "Telegram authentication is not configured."},
    },
)
async def exchange_telegram_auth_result(
    payload: TelegramAuthResultRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokensResponse:
    try:
        padding = (4 - len(payload.tg_auth_result) % 4) % 4
        raw_data = json.loads(
            base64.urlsafe_b64decode(payload.tg_auth_result + "=" * padding)
        )
        tg_payload = TelegramLoginRequest(**raw_data)
    except Exception as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_result",
            message="Invalid Telegram auth result.",
        ) from exc

    try:
        auth_response, refresh_token = await service.telegram_login(
            payload=tg_payload,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except InvalidTelegramLoginError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_login",
            message="Invalid Telegram login data.",
        ) from exc
    except TelegramAuthNotConfiguredError as exc:
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="telegram_auth_not_configured",
            message="Telegram authentication is not configured.",
        ) from exc

    _set_refresh_cookie(response, refresh_token)
    return auth_response


@router.post(
    "/telegram-code",
    response_model=AuthTokensResponse,
    summary="Exchange Telegram login code",
    description="Exchanges a one-time Telegram redirect login code for a bearer access token.",
    responses={
        200: {"description": "Access token returned."},
        401: {"model": ErrorResponse, "description": "Invalid Telegram login code."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
    },
)
async def exchange_telegram_login_code(
    payload: TelegramLoginCodeExchangeRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokensResponse:
    try:
        return await service.exchange_telegram_login_code(payload=payload)
    except InvalidTelegramLoginCodeError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_login_code",
            message="Invalid Telegram login code.",
        ) from exc


@router.post(
    "/refresh",
    response_model=AuthTokensResponse,
    summary="Refresh session",
    description=(
        "Rotates the refresh token stored in the httpOnly cookie and returns a new access token."
    ),
    responses={
        200: {"description": "Session refreshed."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid refresh token.",
            "content": {
                "application/json": {
                    "examples": {
                        "missing": {"value": {"detail": "missing refresh token"}},
                        "invalid": {"value": {"detail": "invalid refresh token"}},
                    }
                }
            },
        },
    },
)
async def refresh(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokensResponse:
    settings = get_settings()
    raw_refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_refresh_token is None:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="missing_refresh_token",
            message="Missing refresh token.",
        )

    try:
        auth_response, new_refresh_token = await service.refresh(
            raw_refresh_token=raw_refresh_token,
        )
    except InvalidRefreshTokenError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_refresh_token",
            message="Invalid refresh token.",
        ) from exc

    _set_refresh_cookie(response, new_refresh_token)
    return auth_response


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout user",
    description="Revokes the current refresh session and clears the refresh cookie.",
    responses={204: {"description": "Session revoked and refresh cookie cleared."}},
)
async def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    settings = get_settings()
    await service.logout(raw_refresh_token=request.cookies.get(settings.refresh_cookie_name))
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/sessions",
    response_model=list[AuthSessionResponse],
    summary="List sessions",
    description="Returns active sessions for the current authenticated user.",
    responses={
        200: {"description": "Active sessions returned."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
    },
)
async def list_sessions(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> list[AuthSessionResponse]:
    return await service.list_sessions(
        user_id=context.user.id,
        current_session_id=context.session.id,
    )


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout all sessions",
    description="Revokes all active sessions for the current user and clears the refresh cookie.",
    responses={
        204: {"description": "All sessions revoked."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
    },
)
async def logout_all(
    response: Response,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.logout_all(user_id=context.user.id)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke session",
    description="Revokes a specific session belonging to the current user.",
    responses={
        204: {"description": "Target session revoked."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Session not found."},
    },
)
async def revoke_session(
    session_id: str,
    response: Response,
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    try:
        await service.revoke_session(user_id=context.user.id, session_id=session_id)
    except SessionNotFoundError as exc:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="session_not_found",
            message="Session not found.",
        ) from exc

    if session_id == context.session.id:
        _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Returns the current authenticated user from the bearer access token.",
    responses={
        200: {"description": "Authenticated user returned."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
            "content": {
                "application/json": {
                    "examples": {
                        "missing": {"value": {"detail": "missing access token"}},
                        "invalid": {"value": {"detail": "invalid access token"}},
                    }
                }
            },
        },
    },
)
async def current_user(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> UserResponse:
    return UserResponse.model_validate(context.user, from_attributes=True)
