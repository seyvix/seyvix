from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.content.schemas import (
    CreateTextNoteRequest,
    FavoriteNoteRequest,
    FolderDetailResponse,
    FolderTreeResponse,
    MergeCollectionRequest,
    NoteCardResponse,
    NoteListResponse,
    NoteSort,
    ReorderNotesRequest,
)
from app.modules.content.service import (
    CollectionMergeConflictError,
    ContentService,
    FolderNotFoundError,
    NoteNotFoundError,
    UploadedContent,
)

router = APIRouter(tags=["content"])


def get_content_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ContentService:
    storage_root = getattr(request.app.state, "content_storage_root", Path("data/content"))
    return ContentService(session, Path(storage_root))


def _not_found(exc: Exception) -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="note_not_found",
        message="Note not found.",
    )


@router.post(
    "/notes/text",
    response_model=NoteCardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create text note",
    description=(
        "Creates a simple text content object, stores it as an object directory with "
        "content.md and manifest.json, and returns the card contract used by the UI."
    ),
    responses={
        201: {"description": "Text note created."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
    },
)
async def create_text_note(
    payload: CreateTextNoteRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> NoteCardResponse:
    return await service.create_text_note(
        owner_user_id=context.user.id,
        text=payload.text,
        title=payload.title,
        folder_path=payload.folder_path,
        tag_names=payload.tag_names,
    )


@router.post(
    "/notes/upload",
    response_model=NoteCardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload note files",
    description=(
        "Uploads one or more files. A single file becomes one content object; multiple files "
        "become separate objects grouped into a new collection."
    ),
    responses={
        201: {"description": "Object or collection created."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
    },
)
async def upload_notes(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
    files: Annotated[list[UploadFile], File(description="Files to ingest as content objects.")],
    title: Annotated[str | None, Form(max_length=512)] = None,
    folder_path: Annotated[str | None, Form(max_length=1024)] = None,
    tag_names: Annotated[list[str] | None, Form()] = None,
) -> NoteCardResponse:
    uploaded_files = [
        UploadedContent(
            filename=file.filename or "file",
            content_type=file.content_type,
            data=await file.read(),
        )
        for file in files
    ]
    return await service.upload_files(
        owner_user_id=context.user.id,
        files=uploaded_files,
        title=title,
        folder_path=folder_path,
        tag_names=tag_names or [],
    )


@router.get(
    "/notes",
    response_model=NoteListResponse,
    summary="List notes",
    description=(
        "Returns note cards for the dashboard. When search is present, collections are expanded "
        "and matching child objects include their collection reference."
    ),
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid access token."}},
)
async def list_notes(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
    search: Annotated[str | None, Query(max_length=512)] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    folder: Annotated[str | None, Query(max_length=1024)] = None,
    folders: Annotated[str | None, Query(max_length=1024)] = None,
    sort: Annotated[NoteSort, Query()] = "newest",
) -> NoteListResponse:
    return await service.list_notes(
        owner_user_id=context.user.id,
        search=search,
        tag_slugs=tags or [],
        folder_path=folders or folder,
        sort=sort,
    )


@router.get(
    "/notes/{note_slug}",
    response_model=NoteCardResponse,
    summary="Get note",
    description="Returns a single note, object, or collection by slug.",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def get_note(
    note_slug: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> NoteCardResponse:
    try:
        return await service.get_note(owner_user_id=context.user.id, slug=note_slug)
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/notes/{note_slug}/download",
    summary="Download note archive",
    description="Downloads the note/object directory as a zip archive for native export flows.",
    responses={
        200: {"description": "Zip archive returned."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def download_note(
    note_slug: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> FileResponse:
    try:
        archive_path = await service.get_download_path(
            owner_user_id=context.user.id, slug=note_slug
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc

    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{note_slug}.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@router.patch(
    "/notes/{note_slug}/favorite",
    response_model=NoteCardResponse,
    summary="Set note favorite state",
    description="Marks or unmarks a note, object, or collection as favorite.",
    responses={
        200: {"description": "Favorite state updated."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def set_note_favorite(
    note_slug: str,
    payload: FavoriteNoteRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> NoteCardResponse:
    try:
        return await service.set_favorite(
            owner_user_id=context.user.id,
            slug=note_slug,
            is_favorite=payload.is_favorite,
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch(
    "/notes/order",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reorder notes",
    description="Stores explicit sort positions used by drag and drop UI ordering.",
    responses={
        204: {"description": "Custom order updated."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "One or more notes were not found."},
    },
)
async def reorder_notes(
    payload: ReorderNotesRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> Response:
    try:
        await service.reorder(
            owner_user_id=context.user.id,
            positions={item.slug: item.position for item in payload.items},
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/notes/collections/merge",
    response_model=NoteCardResponse,
    summary="Merge notes into collection",
    description=(
        "Creates a new collection from two or more non-collection objects, or moves "
        "non-collection objects into an existing collection. Collection-to-collection merge "
        "is rejected."
    ),
    responses={
        200: {"description": "Object moved into existing collection."},
        201: {"description": "New collection created."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "One or more notes were not found."},
        409: {"model": ErrorResponse, "description": "Collection-to-collection merge conflict."},
    },
)
async def merge_collection(
    payload: MergeCollectionRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> Response:
    try:
        card, status_code = await service.merge_collection(
            owner_user_id=context.user.id,
            source_slugs=payload.source_slugs,
            title=payload.title,
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    except CollectionMergeConflictError as exc:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="collection_merge_conflict",
            message="Collection cannot be merged with another collection.",
        ) from exc
    return Response(
        content=card.model_dump_json(),
        media_type="application/json",
        status_code=status_code,
    )


@router.get(
    "/folders",
    response_model=FolderTreeResponse,
    summary="List folder tree",
    description="Returns the category hierarchy used by folder and mind-map pages.",
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid access token."}},
)
async def list_folders(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> FolderTreeResponse:
    return await service.list_folders(owner_user_id=context.user.id)


@router.get(
    "/folders/{folder_path:path}",
    response_model=FolderDetailResponse,
    summary="Get folder detail",
    description="Returns a folder, notes inside it, and tags used by notes in that folder.",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Folder not found."},
    },
)
async def get_folder(
    folder_path: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> FolderDetailResponse:
    try:
        return await service.get_folder_detail(
            owner_user_id=context.user.id,
            folder_path=folder_path,
        )
    except FolderNotFoundError as exc:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="folder_not_found",
            message="Folder not found.",
        ) from exc
