from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.core.config import get_settings
from app.modules.auth.schemas import (
    AuthSessionResponse,
    AuthTokensResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from app.modules.auth.service import (
    AuthContext,
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    SessionNotFoundError,
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


@router.post(
    "/register",
    response_model=AuthTokensResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register user",
    description=(
        "Creates a new user account, starts an authenticated session, returns an access token, "
        "and sets a refresh token in an httpOnly cookie."
    ),
    responses={
        201: {"description": "User created and authenticated."},
        409: {"model": ErrorResponse, "description": "Email already exists."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
    },
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokensResponse:
    try:
        auth_response, refresh_token = await service.register(
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except EmailAlreadyRegisteredError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="email_already_registered",
            message="Email already registered.",
        ) from exc

    _set_refresh_cookie(response, refresh_token)
    return auth_response


@router.post(
    "/login",
    response_model=AuthTokensResponse,
    summary="Login user",
    description=(
        "Authenticates a user by email and password, returns an access token, "
        "and sets a refresh token in an httpOnly cookie."
    ),
    responses={
        200: {"description": "User authenticated."},
        401: {"model": ErrorResponse, "description": "Invalid credentials."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokensResponse:
    try:
        auth_response, refresh_token = await service.login(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except InvalidCredentialsError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_credentials",
            message="Invalid credentials.",
        ) from exc

    _set_refresh_cookie(response, refresh_token)
    return auth_response


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
