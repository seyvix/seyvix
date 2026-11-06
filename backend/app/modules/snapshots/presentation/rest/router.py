from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

import jwt
from fastapi import APIRouter, Cookie, Depends, Query, Request, Security, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.core.config import get_settings
from app.modules.auth.dependencies import bearer_auth_scheme, get_auth_context, get_auth_service
from app.modules.auth.service import AuthContext, AuthService, InvalidAccessTokenError
from app.modules.content.presentation.rest.files import (
    IMMUTABLE_FILE_CACHE,
    storage_file_response,
)
from app.modules.snapshots.schemas import (
    ReprocessSnapshotsRequest,
    ReprocessSnapshotsResponse,
    SnapshotArtifactListResponse,
    SnapshotJobListResponse,
    SnapshotSettingsResponse,
    UpdateSnapshotSettingsRequest,
)
from app.modules.snapshots.service import SnapshotFile, SnapshotNotFoundError, SnapshotService
from app.platform.storage.service import StorageBackend

router = APIRouter(prefix="/snapshots", tags=["snapshots"])
SNAPSHOT_ACCESS_COOKIE: Final = "snapshot_access"
SNAPSHOT_ACCESS_TTL_SECONDS: Final = 15 * 60
# Archived pages are untrusted third-party HTML served from our origin: no scripts, no
# plugins, no outbound loads — only the archived resources themselves.
ARCHIVE_CSP: Final = (
    "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; media-src 'self'; frame-ancestors 'self'; base-uri 'none'; "
    "form-action 'none'"
)


def get_snapshot_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SnapshotService:
    return SnapshotService(session, request.app.state.storage)


def _not_found(code: str = "snapshot_artifact_not_found") -> AppError:
    return AppError(status_code=404, code=code, message="Snapshot artifact not found.")


def _build_snapshot_access_token(*, user_id: str, artifact_id: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "artifact_id": artifact_id,
        "type": "snapshot_access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=SNAPSHOT_ACCESS_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm)


def _decode_snapshot_access_token(*, token: str, artifact_id: str) -> str:
    settings = get_settings()
    payload = jwt.decode(token, settings.auth_jwt_secret, algorithms=[settings.auth_jwt_algorithm])
    if payload.get("type") != "snapshot_access" or payload.get("artifact_id") != artifact_id:
        raise jwt.InvalidTokenError("invalid snapshot access token")
    return str(payload["sub"])


async def _resolve_owner(
    *,
    artifact_id: str,
    auth_service: AuthService,
    authorization: HTTPAuthorizationCredentials | None,
    snapshot_access: str | None,
) -> tuple[str, bool]:
    """Bearer token (API clients) or the scoped cookie set by a previous bearer request
    (lets an <iframe>/<img> load the artifact and its archived resources)."""
    if authorization and authorization.credentials:
        try:
            context = await auth_service.get_auth_context(authorization.credentials.strip())
        except InvalidAccessTokenError as exc:
            raise AppError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="invalid_access_token",
                message="Invalid access token.",
            ) from exc
        return context.user.id, True
    if snapshot_access:
        try:
            user_id = _decode_snapshot_access_token(token=snapshot_access, artifact_id=artifact_id)
            return user_id, False
        except jwt.InvalidTokenError as exc:
            raise AppError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="invalid_snapshot_access_token",
                message="Invalid snapshot access token.",
            ) from exc
    raise AppError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="missing_access_token",
        message="Missing access token.",
    )


def _set_snapshot_access_cookie(response: Response, *, user_id: str, artifact_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SNAPSHOT_ACCESS_COOKIE,
        value=_build_snapshot_access_token(user_id=user_id, artifact_id=artifact_id),
        max_age=SNAPSHOT_ACCESS_TTL_SECONDS,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=f"{settings.api_prefix}/snapshots/artifacts/{artifact_id}",
    )


async def file_response(
    request: Request, storage: StorageBackend, file: SnapshotFile, *, archive: bool = False
) -> Response:
    """Serve without temp files (sendfile/Range/ETag locally, ranged streaming on S3).
    Artifact ids change on every re-snapshot, so responses are cacheable."""
    if file.key is None:
        response: Response = Response(
            content=file.text or "",
            media_type=file.mime_type,
            headers={"Cache-Control": IMMUTABLE_FILE_CACHE, "X-Content-Type-Options": "nosniff"},
        )
    else:
        response = await storage_file_response(
            request,
            storage,
            key=file.key,
            filename=file.filename,
            media_type=file.mime_type,
            cache_control=IMMUTABLE_FILE_CACHE,
        )
    if archive:
        response.headers["Content-Security-Policy"] = ARCHIVE_CSP
    return response


@router.get(
    "/settings",
    response_model=SnapshotSettingsResponse,
    summary="Get snapshot settings",
    description=(
        "Returns effective snapshot settings for the current user and nullable per-user "
        "overrides. Null override values inherit the server defaults."
    ),
)
async def get_snapshot_settings(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> SnapshotSettingsResponse:
    return await service.get_user_settings(context.user.id)


@router.patch(
    "/settings",
    response_model=SnapshotSettingsResponse,
    summary="Update snapshot settings",
    description=(
        "Stores nullable per-user overrides for snapshot formats. Omitted fields keep their "
        "current value; explicit null resets a format to the server default."
    ),
)
async def update_snapshot_settings(
    payload: UpdateSnapshotSettingsRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> SnapshotSettingsResponse:
    return await service.update_user_settings(owner_user_id=context.user.id, payload=payload)


@router.get(
    "/jobs",
    response_model=SnapshotJobListResponse,
    summary="List snapshot jobs",
    description="Snapshot jobs owned by the current user, optionally for one content object.",
)
async def list_snapshot_jobs(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    content_object_id: Annotated[str | None, Query(max_length=36)] = None,
) -> SnapshotJobListResponse:
    return await service.list_jobs(
        owner_user_id=context.user.id, content_object_id=content_object_id
    )


@router.get(
    "/artifacts",
    response_model=SnapshotArtifactListResponse,
    summary="List snapshot artifacts",
    description="Ready snapshot artifacts owned by the current user.",
)
async def list_snapshot_artifacts(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    content_object_id: Annotated[str | None, Query(max_length=36)] = None,
) -> SnapshotArtifactListResponse:
    return await service.list_artifacts(
        owner_user_id=context.user.id, content_object_id=content_object_id
    )


@router.post(
    "/reprocess",
    response_model=ReprocessSnapshotsResponse,
    summary="Reprocess snapshot jobs",
    description=(
        "Queues snapshot jobs for owned content or a specific source asset. "
        "When job_types is omitted, Markdown extraction is queued."
    ),
    responses={404: {"model": ErrorResponse, "description": "Content or asset not found."}},
)
async def reprocess_snapshots(
    payload: ReprocessSnapshotsRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> ReprocessSnapshotsResponse:
    try:
        return await service.reprocess(owner_user_id=context.user.id, payload=payload)
    except SnapshotNotFoundError as exc:
        raise AppError(
            status_code=404, code="snapshot_source_not_found", message="Snapshot source not found."
        ) from exc


@router.get(
    "/artifacts/{artifact_id}",
    summary="Get snapshot artifact file",
    description="Streams a generated snapshot artifact file.",
    responses={
        200: {"description": "Snapshot artifact file returned."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Snapshot artifact not found."},
    },
)
async def get_snapshot_artifact_file(
    artifact_id: str,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    authorization: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_auth_scheme)
    ] = None,
    snapshot_access: Annotated[str | None, Cookie(alias=SNAPSHOT_ACCESS_COOKIE)] = None,
) -> Response:
    owner_user_id, used_bearer = await _resolve_owner(
        artifact_id=artifact_id,
        auth_service=auth_service,
        authorization=authorization,
        snapshot_access=snapshot_access,
    )
    try:
        file = await service.get_artifact_file(owner_user_id=owner_user_id, artifact_id=artifact_id)
    except SnapshotNotFoundError as exc:
        raise _not_found() from exc
    response = await file_response(
        request, request.app.state.storage, file, archive=file.mime_type == "text/html"
    )
    if used_bearer:
        _set_snapshot_access_cookie(response, user_id=owner_user_id, artifact_id=artifact_id)
    return response


@router.get(
    "/artifacts/{artifact_id}/resources/{filename}",
    summary="Get snapshot archive resource",
    description=(
        "Streams a static resource (CSS, image, font) of a webpage HTML archive. Access is "
        "granted by the short-lived scoped snapshot cookie or a bearer token."
    ),
    responses={
        200: {"description": "Resource file returned."},
        401: {"model": ErrorResponse, "description": "Missing or invalid snapshot access cookie."},
        404: {"model": ErrorResponse, "description": "Resource not found."},
    },
)
async def get_snapshot_artifact_resource(
    artifact_id: str,
    filename: str,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    authorization: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_auth_scheme)
    ] = None,
    snapshot_access: Annotated[str | None, Cookie(alias=SNAPSHOT_ACCESS_COOKIE)] = None,
) -> Response:
    owner_user_id, _ = await _resolve_owner(
        artifact_id=artifact_id,
        auth_service=auth_service,
        authorization=authorization,
        snapshot_access=snapshot_access,
    )
    try:
        file = await service.get_artifact_resource(
            owner_user_id=owner_user_id, artifact_id=artifact_id, filename=filename
        )
    except SnapshotNotFoundError as exc:
        raise _not_found() from exc
    return await file_response(request, request.app.state.storage, file, archive=True)
