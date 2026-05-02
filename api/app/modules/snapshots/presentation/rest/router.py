from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.snapshots.schemas import (
    SnapshotArtifactListResponse,
    SnapshotJobListResponse,
    SnapshotSettingsResponse,
    UpdateSnapshotSettingsRequest,
)
from app.modules.snapshots.service import SnapshotArtifactNotFoundError, SnapshotService

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


def get_snapshot_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SnapshotService:
    storage_root = getattr(request.app.state, "content_storage_root", Path("data/content"))
    storage_backend = getattr(request.app.state, "storage_backend", None)
    return SnapshotService(session, Path(storage_root), storage_backend=storage_backend)


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
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> FileResponse:
    try:
        path, mime_type, filename = await service.get_artifact_file(
            owner_user_id=context.user.id,
            artifact_id=artifact_id,
        )
    except SnapshotArtifactNotFoundError as exc:
        raise AppError(
            status_code=404,
            code="snapshot_artifact_not_found",
            message="Snapshot artifact not found.",
        ) from exc
    return FileResponse(path, media_type=mime_type, filename=filename)
