from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import APIRouter, Cookie, Depends, Query, Request, Security, status
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.auth.presentation.rest.router import (
    bearer_auth_scheme,
    get_auth_context,
    get_auth_service,
)
from app.modules.auth.service import AuthContext, AuthService, InvalidAccessTokenError
from app.modules.snapshots.schemas import (
    ReprocessSnapshotsRequest,
    ReprocessSnapshotsResponse,
    SnapshotArtifactListResponse,
    SnapshotJobListResponse,
    SnapshotSettingsResponse,
    UpdateSnapshotSettingsRequest,
)
from app.modules.snapshots.service import SnapshotArtifactNotFoundError, SnapshotService

router = APIRouter(prefix="/snapshots", tags=["snapshots"])
SNAPSHOT_ACCESS_COOKIE = "snapshot_access"
SNAPSHOT_ACCESS_TTL_SECONDS = 15 * 60
logger = get_logger(__name__)


def get_snapshot_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SnapshotService:
    storage_root = getattr(request.app.state, "content_storage_root", Path("data/content"))
    storage_backend = getattr(request.app.state, "storage_backend", None)
    return SnapshotService(session, Path(storage_root), storage_backend=storage_backend)


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
    payload = jwt.decode(
        token,
        settings.auth_jwt_secret,
        algorithms=[settings.auth_jwt_algorithm],
    )
    if payload.get("type") != "snapshot_access" or payload.get("artifact_id") != artifact_id:
        raise jwt.InvalidTokenError("invalid snapshot access token")
    return str(payload["sub"])


async def _resolve_snapshot_owner_user_id(
    *,
    artifact_id: str,
    auth_service: AuthService,
    authorization: HTTPAuthorizationCredentials | None,
    snapshot_access: str | None,
) -> tuple[str, bool]:
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
            return (
                _decode_snapshot_access_token(
                    token=snapshot_access,
                    artifact_id=artifact_id,
                ),
                False,
            )
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


@router.get(
    "/settings",
    response_model=SnapshotSettingsResponse,
    summary="Get snapshot settings",
    description=(
        "Returns effective snapshot archive settings for the current user and nullable "
        "per-user overrides. Null override values inherit global environment settings."
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
        "current value; explicit null resets a format to the global environment default."
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
    description=(
        "Returns snapshot worker jobs owned by the current user. The optional content_object_id "
        "filter is useful for clients that want to poll processing status for a material."
    ),
)
async def list_snapshot_jobs(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    content_object_id: Annotated[str | None, Query(max_length=36)] = None,
) -> SnapshotJobListResponse:
    return await service.list_jobs(
        owner_user_id=context.user.id,
        content_object_id=content_object_id,
    )


@router.get(
    "/artifacts",
    response_model=SnapshotArtifactListResponse,
    summary="List snapshot artifacts",
    description=(
        "Returns ready snapshot artifacts owned by the current user. Clients can use this "
        "endpoint after polling jobs to show available Markdown, HTML, PDF, screenshot, and "
        "thumbnail views."
    ),
)
async def list_snapshot_artifacts(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    content_object_id: Annotated[str | None, Query(max_length=36)] = None,
) -> SnapshotArtifactListResponse:
    return await service.list_artifacts(
        owner_user_id=context.user.id,
        content_object_id=content_object_id,
    )


@router.post(
    "/reprocess",
    response_model=ReprocessSnapshotsResponse,
    summary="Reprocess snapshot jobs",
    description=(
        "Queues snapshot jobs for existing owned content or a specific source asset. "
        "When job_types is omitted, Markdown extraction is queued."
    ),
    responses={
        200: {"description": "Snapshot jobs queued."},
        404: {"model": ErrorResponse, "description": "Content object or asset not found."},
    },
)
async def reprocess_snapshots(
    payload: ReprocessSnapshotsRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> ReprocessSnapshotsResponse:
    try:
        return await service.reprocess(owner_user_id=context.user.id, payload=payload)
    except SnapshotArtifactNotFoundError as exc:
        raise AppError(
            status_code=404,
            code="snapshot_source_not_found",
            message="Snapshot source not found.",
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
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_auth_scheme),
    ] = None,
    snapshot_access: Annotated[str | None, Cookie(alias=SNAPSHOT_ACCESS_COOKIE)] = None,
) -> FileResponse:
    owner_user_id, used_bearer = await _resolve_snapshot_owner_user_id(
        artifact_id=artifact_id,
        auth_service=auth_service,
        authorization=authorization,
        snapshot_access=snapshot_access,
    )
    logger.info(
        "snapshot.rest.artifact.request",
        artifact_id=artifact_id,
        owner_user_id=owner_user_id,
        auth_method="bearer" if used_bearer else "snapshot_cookie",
    )
    try:
        path, mime_type, filename = await service.get_artifact_file(
            owner_user_id=owner_user_id,
            artifact_id=artifact_id,
        )
    except SnapshotArtifactNotFoundError as exc:
        raise AppError(
            status_code=404,
            code="snapshot_artifact_not_found",
            message="Snapshot artifact not found.",
        ) from exc
    response = FileResponse(
        path,
        media_type=mime_type,
        filename=filename,
        content_disposition_type="inline",
    )
    if used_bearer:
        _set_snapshot_access_cookie(response, user_id=owner_user_id, artifact_id=artifact_id)
    logger.info(
        "snapshot.rest.artifact.response",
        artifact_id=artifact_id,
        filename=filename,
        mime_type=mime_type,
        path=str(path),
        cookie_set=used_bearer,
    )
    return response


@router.get(
    "/artifacts/{artifact_id}/resources/{filename}",
    summary="Get snapshot archive resource",
    description=(
        "Streams a static resource file (CSS, image, font) belonging to a webpage HTML archive. "
        "Access is granted by a short-lived scoped snapshot cookie."
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
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_auth_scheme),
    ] = None,
    snapshot_access: Annotated[str | None, Cookie(alias=SNAPSHOT_ACCESS_COOKIE)] = None,
) -> Response:
    owner_user_id, _ = await _resolve_snapshot_owner_user_id(
        artifact_id=artifact_id,
        auth_service=auth_service,
        authorization=authorization,
        snapshot_access=snapshot_access,
    )
    logger.info(
        "snapshot.rest.resource.request",
        artifact_id=artifact_id,
        filename=filename,
        owner_user_id=owner_user_id,
        has_cookie=snapshot_access is not None,
        has_bearer=authorization is not None and bool(authorization.credentials),
    )
    try:
        data, content_type = await service.get_artifact_resource(
            owner_user_id=owner_user_id,
            artifact_id=artifact_id,
            filename=filename,
        )
    except SnapshotArtifactNotFoundError as exc:
        raise AppError(
            status_code=404,
            code="snapshot_artifact_not_found",
            message="Snapshot artifact not found.",
        ) from exc
    logger.info(
        "snapshot.rest.resource.response",
        artifact_id=artifact_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
    )
    return Response(content=data, media_type=content_type)
