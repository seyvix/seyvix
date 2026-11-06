"""Telegram sign-in and session endpoints.

No GET endpoint creates a session (login-CSRF): browser redirects only carry data back to the SPA,
which then calls a JSON POST endpoint (cross-site JSON POSTs need a CORS preflight we never allow).
"""

import base64
import binascii
import json
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.core.config import get_settings
from app.modules.auth.access import AccessDeniedError, access_denied_details
from app.modules.auth.avatar import get_telegram_avatar
from app.modules.auth.dependencies import (
    auth_app_error,
    bearer_auth_scheme,
    get_auth_context,
    get_auth_context_from_bearer_or_refresh_cookie,
    get_auth_service,
)
from app.modules.auth.schemas import (
    AuthSessionResponse,
    AuthTokensResponse,
    TelegramAuthResultRequest,
    TelegramLoginCodeExchangeRequest,
    TelegramLoginRequest,
    TelegramOidcCodeExchangeRequest,
    TelegramWebAppLoginRequest,
    UserResponse,
)
from app.modules.auth.security import (
    TelegramIdentity,
    build_pkce_code_challenge,
    generate_token,
    tokens_equal,
)
from app.modules.auth.service import (
    AuthContext,
    AuthError,
    AuthService,
    TelegramAuthNotConfiguredError,
)

__all__ = [
    "bearer_auth_scheme",
    "get_auth_context",
    "get_auth_context_from_bearer_or_refresh_cookie",
    "get_auth_service",
    "router",
]

router = APIRouter(prefix="/auth", tags=["auth"])

TELEGRAM_OIDC_STATE_COOKIE = "telegram_oidc_state"
TELEGRAM_OIDC_CODE_VERIFIER_COOKIE = "telegram_oidc_code_verifier"
TELEGRAM_LOGIN_STATE_COOKIE = "telegram_login_state"
LOGIN_STATE_MAX_AGE_SECONDS = 600

LOGIN_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Invalid Telegram login data."},
    403: {"model": ErrorResponse, "description": "access_denied or account_disabled."},
    503: {"model": ErrorResponse, "description": "Telegram authentication is not configured."},
}

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AuthContextDep = Annotated[AuthContext, Depends(get_auth_context)]


def _auth_cookie_path() -> str:
    return f"{get_settings().api_prefix}/auth"


def _set_short_lived_cookie(response: Response, name: str, value: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=name,
        value=value,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=_auth_cookie_path(),
        max_age=LOGIN_STATE_MAX_AGE_SECONDS,
    )


def _clear_cookies(response: Response, *names: str) -> None:
    for name in names:
        response.delete_cookie(key=name, path=_auth_cookie_path())


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    # Scoped to the API (cookie-authenticated asset URLs live there), never sent to the SPA.
    response.delete_cookie(key=settings.refresh_cookie_name, path="/")
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=settings.api_prefix,
        max_age=settings.refresh_token_absolute_ttl_days * 86400,
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    for path in ("/", settings.api_prefix):
        response.delete_cookie(key=settings.refresh_cookie_name, path=path)


def _client_meta(request: Request) -> dict[str, str | None]:
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip_address": request.client.host if request.client else None,
    }


def _login_error(exc: AuthError | AccessDeniedError) -> AppError:
    if isinstance(exc, AccessDeniedError):
        return AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="access_denied",
            message=(
                f"Access is restricted. Ask the administrator to allow Telegram ID "
                f"{exc.telegram_user_id}."
            ),
            details=access_denied_details(exc.telegram_user_id, exc.username),
        )
    return auth_app_error(exc)


async def _login(
    service: AuthService,
    identity: TelegramIdentity,
    request: Request,
    response: Response,
) -> AuthTokensResponse:
    try:
        tokens, refresh_token = await service.login(identity, **_client_meta(request))
    except (AuthError, AccessDeniedError) as exc:
        raise _login_error(exc) from exc
    _set_refresh_cookie(response, refresh_token)
    return tokens


def _dev_login_redirect() -> RedirectResponse:
    """Dev only: bind a single-use nonce to this browser, then let the SPA POST it back."""
    try:
        AuthService.dev_identity()
    except AuthError as exc:
        raise auth_app_error(exc) from exc
    nonce = generate_token()
    response = RedirectResponse(
        f"{get_settings().telegram_login_redirect_url}?{urlencode({'code': nonce})}",
        status_code=status.HTTP_302_FOUND,
    )
    _set_short_lived_cookie(response, TELEGRAM_LOGIN_STATE_COOKIE, nonce)
    return response


@router.get("/telegram-login", include_in_schema=False)
async def telegram_login_redirect() -> RedirectResponse:
    """Start sign-in: Telegram OIDC (PKCE + state cookie), or the dev login when enabled."""
    settings = get_settings()
    if settings.telegram_dev_login_enabled and not settings.is_production:
        return _dev_login_redirect()
    if not settings.telegram_oidc_client_id or not settings.telegram_oidc_client_secret:
        raise auth_app_error(TelegramAuthNotConfiguredError())
    state = generate_token()
    code_verifier = generate_token()
    authorization_url = f"{settings.telegram_oidc_authorization_url}?" + urlencode(
        {
            "client_id": settings.telegram_oidc_client_id,
            "redirect_uri": settings.telegram_login_redirect_url,
            "response_type": "code",
            "scope": settings.telegram_oidc_scope,
            "state": state,
            "code_challenge": build_pkce_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        },
    )
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    _set_short_lived_cookie(response, TELEGRAM_OIDC_STATE_COOKIE, state)
    _set_short_lived_cookie(response, TELEGRAM_OIDC_CODE_VERIFIER_COOKIE, code_verifier)
    return response


@router.get("/telegram-dev-login", include_in_schema=False)
async def telegram_dev_login() -> RedirectResponse:
    return _dev_login_redirect()


@router.get(
    "/telegram-callback",
    summary="Telegram Login Widget redirect target",
    description=(
        "Forwards the signed Login Widget parameters to the SPA as a `#tgAuthResult=` fragment; "
        "the SPA exchanges it via POST /auth/telegram-result. Creates no session itself."
    ),
    responses={302: {"description": "Redirect to the SPA auth callback."}},
)
async def telegram_callback(request: Request) -> RedirectResponse:
    redirect_url = get_settings().telegram_login_redirect_url
    params = dict(request.query_params)
    if not params.get("hash"):
        return RedirectResponse(
            f"{redirect_url}?{urlencode({'error': 'invalid_telegram_login'})}",
            status_code=status.HTTP_302_FOUND,
        )
    encoded = base64.urlsafe_b64encode(
        json.dumps(params, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return RedirectResponse(
        f"{redirect_url}#{urlencode({'tgAuthResult': encoded.rstrip('=')})}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post(
    "/telegram-login",
    response_model=AuthTokensResponse,
    summary="Login with Telegram Login Widget data",
    responses=LOGIN_RESPONSES,
)
async def telegram_login(
    payload: TelegramLoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AuthTokensResponse:
    try:
        identity = service.verify_widget_login(payload)
    except AuthError as exc:
        raise auth_app_error(exc) from exc
    return await _login(service, identity, request, response)


@router.post(
    "/telegram-result",
    response_model=AuthTokensResponse,
    summary="Exchange tgAuthResult (oauth.telegram.org / widget redirect)",
    responses=LOGIN_RESPONSES,
)
async def exchange_telegram_auth_result(
    payload: TelegramAuthResultRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AuthTokensResponse:
    try:
        padding = "=" * ((4 - len(payload.tg_auth_result) % 4) % 4)
        raw_data = json.loads(base64.urlsafe_b64decode(payload.tg_auth_result + padding))
        if not isinstance(raw_data, dict):
            raise ValueError("tgAuthResult is not an object")
        identity = service.verify_widget_login(TelegramLoginRequest.model_validate(raw_data))
    except (ValueError, binascii.Error, ValidationError) as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_result",
            message="Invalid Telegram auth result.",
        ) from exc
    except AuthError as exc:
        raise auth_app_error(exc) from exc
    return await _login(service, identity, request, response)


@router.post(
    "/telegram-oidc-code",
    response_model=AuthTokensResponse,
    summary="Exchange Telegram OIDC authorization code",
    responses=LOGIN_RESPONSES,
)
async def exchange_telegram_oidc_code(
    payload: TelegramOidcCodeExchangeRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AuthTokensResponse:
    expected_state = request.cookies.get(TELEGRAM_OIDC_STATE_COOKIE)
    code_verifier = request.cookies.get(TELEGRAM_OIDC_CODE_VERIFIER_COOKIE)
    _clear_cookies(response, TELEGRAM_OIDC_STATE_COOKIE, TELEGRAM_OIDC_CODE_VERIFIER_COOKIE)
    if not code_verifier or not tokens_equal(expected_state, payload.state):
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_oidc_state",
            message="Invalid Telegram OIDC state.",
        )
    try:
        identity = await service.verify_oidc_login(code=payload.code, code_verifier=code_verifier)
    except AuthError as exc:
        raise auth_app_error(exc) from exc
    return await _login(service, identity, request, response)


@router.post(
    "/telegram-web-app",
    response_model=AuthTokensResponse,
    summary="Login with Telegram Mini App initData",
    responses=LOGIN_RESPONSES,
)
async def telegram_web_app_login(
    payload: TelegramWebAppLoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AuthTokensResponse:
    try:
        identity = service.verify_web_app_login(payload.init_data)
    except AuthError as exc:
        raise auth_app_error(exc) from exc
    return await _login(service, identity, request, response)


@router.post(
    "/telegram-code",
    response_model=AuthTokensResponse,
    summary="Exchange the dev login code",
    description=(
        "Development only. Completes GET /auth/telegram-dev-login: the code must match the "
        "single-use state cookie set on that redirect."
    ),
    responses=LOGIN_RESPONSES,
)
async def exchange_telegram_login_code(
    payload: TelegramLoginCodeExchangeRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AuthTokensResponse:
    expected = request.cookies.get(TELEGRAM_LOGIN_STATE_COOKIE)
    _clear_cookies(response, TELEGRAM_LOGIN_STATE_COOKIE)
    if not tokens_equal(expected, payload.code):
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_telegram_login_code",
            message="Invalid Telegram login code.",
        )
    try:
        identity = service.dev_identity()
    except AuthError as exc:
        raise auth_app_error(exc) from exc
    return await _login(service, identity, request, response)


@router.post(
    "/refresh",
    response_model=AuthTokensResponse,
    summary="Refresh session",
    description="Rotates the httpOnly refresh cookie and returns a new access token.",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid refresh token."},
        403: {"model": ErrorResponse, "description": "Access was revoked (access_denied)."},
    },
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AuthTokensResponse:
    raw_refresh_token = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw_refresh_token:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="missing_refresh_token",
            message="Missing refresh token.",
        )
    try:
        tokens, new_refresh_token = await service.refresh(raw_refresh_token=raw_refresh_token)
    except (AuthError, AccessDeniedError) as exc:
        raise _login_error(exc) from exc
    if new_refresh_token is not None:
        _set_refresh_cookie(response, new_refresh_token)
    return tokens


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout",
    description="Revokes the current session and clears the refresh cookie.",
)
async def logout(request: Request, service: AuthServiceDep) -> Response:
    await service.logout(raw_refresh_token=request.cookies.get(get_settings().refresh_cookie_name))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get(
    "/sessions",
    response_model=list[AuthSessionResponse],
    summary="List active sessions of the current user",
)
async def list_sessions(
    context: AuthContextDep,
    service: AuthServiceDep,
) -> list[AuthSessionResponse]:
    return await service.list_sessions(
        user_id=context.user.id,
        current_session_id=context.session.id,
    )


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout all sessions",
)
async def logout_all(context: AuthContextDep, service: AuthServiceDep) -> Response:
    await service.logout_all(user_id=context.user.id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a session of the current user",
    responses={404: {"model": ErrorResponse, "description": "Session not found."}},
)
async def revoke_session(
    session_id: str,
    context: AuthContextDep,
    service: AuthServiceDep,
) -> Response:
    try:
        await service.revoke_session(user_id=context.user.id, session_id=session_id)
    except AuthError as exc:
        raise auth_app_error(exc) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if session_id == context.session.id:
        _clear_refresh_cookie(response)
    return response


@router.get(
    "/me/avatar",
    summary="Current user's Telegram avatar",
    description="Proxies the Telegram avatar (Telegram hosts only, images only, cached).",
    responses={404: {"model": ErrorResponse, "description": "Avatar is not available."}},
)
async def current_user_avatar(
    context: Annotated[AuthContext, Depends(get_auth_context_from_bearer_or_refresh_cookie)],
) -> Response:
    avatar = await get_telegram_avatar(
        telegram_id=context.user.telegram_id,
        photo_url=context.user.telegram_photo_url,
    )
    if avatar is None:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="avatar_not_available",
            message="Avatar is not available.",
        )
    return Response(
        content=avatar.content,
        media_type=avatar.media_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/me", response_model=UserResponse, summary="Current user")
async def current_user(context: AuthContextDep) -> UserResponse:
    return UserResponse.model_validate(context.user, from_attributes=True)
