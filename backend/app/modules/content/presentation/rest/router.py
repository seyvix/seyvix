from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.core.config import get_settings
from app.modules.auth.presentation.rest.router import (
    get_auth_context,
    get_auth_context_from_bearer_or_refresh_cookie,
)
from app.modules.auth.service import AuthContext
from app.modules.content.app_note import (
    AppCardNoteListResponse,
    AppNote,
    AppNoteListResponse,
    FileUploadAppResponse,
    FolderDetailAppResponse,
    NoteChangesResponse,
    note_card_to_app_card_note,
    note_card_to_app_note,
    upload_result_to_json_bytes,
)
from app.modules.content.presentation.rest.files import (
    IMMUTABLE_FILE_CACHE,
    MUTABLE_FILE_CACHE,
    content_disposition,
    storage_file_response,
)
from app.modules.content.schemas import (
    BulkDeleteRequest,
    CreateNoteRequest,
    FavoriteNoteRequest,
    FolderTreeResponse,
    LinkSnapshotDecisionRequest,
    MergeNotesRequest,
    NoteCardResponse,
    NoteSort,
    RemoveCollectionItemsRequest,
    ReorderNotesRequest,
    UpdateNoteRequest,
)
from app.modules.content.service import (
    ContentService,
    FolderNotFoundError,
    NoteNotFoundError,
    ThumbnailPendingError,
    ThumbnailUnavailableError,
)
from app.modules.content.uploads import spool_upload_files
from app.modules.search.schemas import SearchFilters, SearchMode
from app.modules.search.service import SearchService, SearchValidationError

router = APIRouter(tags=["content"])
NoteListView = Literal["full", "card"]
CARD_VIEW_TEXT_CONTENT_LIMIT = 240
CARD_VIEW_MAX_OBJECTS = 6
CARD_VIEW_SEARCH_MATCH_TEXT_LIMIT = 240
SEARCH_CANDIDATE_LIMIT = 500


def get_content_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ContentService:
    return ContentService(session, request.app.state.storage)


def _not_found(exc: Exception) -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="note_not_found",
        message="Note not found.",
    )


def _parse_filter_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message=f"{field_name} must be an ISO date or datetime.",
        ) from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _card_json(cards: list[NoteCardResponse]) -> list[object]:
    return [
        note_card_to_app_card_note(
            card,
            text_content_limit=CARD_VIEW_TEXT_CONTENT_LIMIT,
            max_objects=CARD_VIEW_MAX_OBJECTS,
            search_match_text_limit=CARD_VIEW_SEARCH_MATCH_TEXT_LIMIT,
        )
        for card in cards
    ]


@router.post(
    "/notes",
    response_model=AppNote,
    status_code=status.HTTP_201_CREATED,
    summary="Create note object",
    description=(
        "Creates a content object from text or from previously uploaded temporary files. "
        "A plain HTTP(S) URL is stored as a link object for website snapshot processing. "
        "Multiple file uploads create a collection with separate child objects."
    ),
    responses={
        201: {"description": "Note object created."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Uploaded file not found."},
        422: {
            "model": ErrorResponse,
            "description": "Validation error in input payload.",
        },
    },
)
async def create_note(
    payload: CreateNoteRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(
            await service.create_note(
                owner_user_id=context.user.id,
                media_type=payload.media_type,
                text=payload.text,
                title=payload.title,
                folder_path=payload.folder_path,
                tag_names=payload.tag_names,
                file_upload_ids=payload.file_upload_ids,
            )
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/notes/file/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload note files",
    description=(
        "Uploads one file into temporary storage by default. If object_id is provided, the file "
        "is added to that object, creating it when needed. If create_object=true is provided "
        "without object_id, the server creates a new object id for this file."
    ),
    responses={
        201: {
            "description": (
                "Temporary upload metadata or created object returned "
                "(camelCase App note when object is present)."
            ),
            "model": FileUploadAppResponse,
        },
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        422: {
            "model": ErrorResponse,
            "description": "Validation error in input payload.",
        },
    },
)
async def upload_note_files(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
    file: Annotated[
        list[UploadFile] | None,
        File(alias="file", description="Files to upload."),
    ] = None,
    files: Annotated[
        list[UploadFile] | None,
        File(alias="files", description="Files to upload."),
    ] = None,
    files_array: Annotated[
        list[UploadFile] | None,
        File(alias="files[]", description="Files to upload."),
    ] = None,
    create_object: Annotated[bool, Form()] = False,
    object_id: Annotated[str | None, Form(max_length=36)] = None,
    title: Annotated[str | None, Form(max_length=512)] = None,
    folder_path: Annotated[str | None, Form(max_length=1024)] = None,
    tag_names: Annotated[list[str] | None, Form()] = None,
) -> Response:
    files_to_upload = [*(file or []), *(files or []), *(files_array or [])]
    if not files_to_upload:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Request validation failed.",
            details=[
                {
                    "type": "missing",
                    "location": ["body", "file"],
                    "message": "At least one file is required.",
                }
            ],
        )
    async with spool_upload_files(
        files_to_upload, max_bytes=get_settings().max_upload_bytes
    ) as uploaded_files:
        try:
            result = await service.upload_files(
                owner_user_id=context.user.id,
                files=uploaded_files,
                title=title,
                folder_path=folder_path,
                tag_names=tag_names or [],
                create_or_attach_object=create_object or object_id is not None,
                object_id=object_id,
            )
        except NoteNotFoundError as exc:
            raise _not_found(exc) from exc
    return Response(
        content=upload_result_to_json_bytes(result),
        media_type="application/json",
        status_code=status.HTTP_201_CREATED,
    )


@router.get(
    "/notes",
    response_model=AppNoteListResponse,
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
    search_mode: Annotated[SearchMode, Query()] = "hybrid",
    tags: Annotated[list[str] | None, Query()] = None,
    folder: Annotated[str | None, Query(max_length=1024)] = None,
    folders: Annotated[str | None, Query(max_length=1024)] = None,
    types: Annotated[list[str] | None, Query()] = None,
    sources: Annotated[list[str] | None, Query()] = None,
    favorite: Annotated[bool | None, Query()] = None,
    created_after: Annotated[str | None, Query(max_length=64)] = None,
    created_before: Annotated[str | None, Query(max_length=64)] = None,
    sort: Annotated[NoteSort, Query()] = "newest",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    view: Annotated[
        NoteListView,
        Query(description="Use 'card' to trim large text bodies for dashboard cards."),
    ] = "full",
) -> AppNoteListResponse | Response:
    created_after_dt = _parse_filter_datetime(created_after, "created_after")
    created_before_dt = _parse_filter_datetime(created_before, "created_before")
    folder_path = folders or folder
    normalized_search = search.strip() if search else None
    search_matches = None
    if normalized_search:
        try:
            search_matches = await SearchService(service.session).search_content_object_matches(
                owner_user_id=context.user.id,
                query=normalized_search,
                limit=SEARCH_CANDIDATE_LIMIT,
                mode=search_mode,
                filters=SearchFilters(
                    tags=tags or [],
                    folder_path=folder_path,
                    content_types=types or [],
                    source_providers=sources or [],
                    is_favorite=favorite,
                    created_at_from=created_after_dt,
                    created_at_to=created_before_dt,
                ),
            )
        except SearchValidationError as exc:
            raise AppError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="validation_error",
                message="Search query must not be empty.",
            ) from exc
    lst = await service.list_notes(
        owner_user_id=context.user.id,
        search_result_ids=list(search_matches) if search_matches is not None else None,
        search_matches_by_object_id=search_matches,
        tag_slugs=tags or [],
        folder_path=folder_path,
        content_types=types or [],
        source_providers=sources or [],
        is_favorite=favorite,
        created_at_from=created_after_dt,
        created_at_to=created_before_dt,
        sort=sort,
        card_view=view == "card",
        limit=limit,
        offset=offset,
    )
    if view == "card":
        payload = AppCardNoteListResponse(
            items=_card_json(lst.items),  # type: ignore[arg-type]
            nextOffset=lst.next_offset,
        )
        return Response(
            content=payload.model_dump_json(by_alias=True, exclude_none=True),
            media_type="application/json",
        )
    return AppNoteListResponse(
        items=[note_card_to_app_note(n) for n in lst.items],
        nextOffset=lst.next_offset,
    )


@router.get(
    "/notes/changes",
    response_model=NoteChangesResponse,
    summary="Note change feed",
    description=(
        "Cards (same schema as `GET /notes?view=card`) changed since `since`, ids removed from "
        "the top-level list (trashed, deleted or moved into a collection) and the next cursor. "
        "`reset=true` (cursor missing, invalid or too old) means: refetch lists, keep cursor. "
        "When `has_more` is true call again immediately with the new cursor."
    ),
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid access token."}},
)
async def list_note_changes(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
    since: Annotated[str | None, Query(max_length=64)] = None,
) -> Response:
    result = await service.list_changes(owner_user_id=context.user.id, since=since)
    payload = NoteChangesResponse(
        cursor=result.changes.cursor,
        notes=_card_json(result.cards),  # type: ignore[arg-type]
        removed_ids=result.changes.removed_ids,
        reset=result.changes.reset,
        has_more=result.changes.has_more,
    )
    return Response(
        content=payload.model_dump_json(by_alias=True, exclude_none=True),
        media_type="application/json",
    )


@router.delete(
    "/notes",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bulk delete notes",
    description="Moves notes to trash when trash is enabled, otherwise permanently deletes them.",
    responses={
        204: {"description": "Notes deleted."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
    },
)
async def bulk_delete_notes(
    payload: BulkDeleteRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> Response:
    await service.delete_notes(
        owner_user_id=context.user.id,
        slugs=payload.slugs,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/notes/trash",
    response_model=AppNoteListResponse,
    summary="List deleted notes",
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid access token."}},
)
async def list_trash(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNoteListResponse:
    lst = await service.list_trash(owner_user_id=context.user.id)
    return AppNoteListResponse(items=[note_card_to_app_note(n) for n in lst.items])


@router.post(
    "/notes/trash/cleanup",
    summary="Permanently delete expired trash notes",
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid access token."}},
)
async def cleanup_trash(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> dict[str, int]:
    deleted_count = await service.cleanup_expired_trash(owner_user_id=context.user.id)
    return {"deleted_count": deleted_count}


@router.patch(
    "/notes/order",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reorder notes",
    description="Stores explicit sort positions used by drag and drop UI ordering.",
    responses={
        204: {"description": "Custom order updated."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {
            "model": ErrorResponse,
            "description": "One or more notes were not found.",
        },
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
    "/notes/merge",
    response_model=AppNote,
    summary="Merge notes",
    description=(
        "Moves source objects or collection items into the target object. If the target is not "
        "a collection yet, it is converted into one while preserving its previous content as the "
        "first child object."
    ),
    responses={
        200: {"description": "Sources moved into target collection."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {
            "model": ErrorResponse,
            "description": "One or more notes were not found.",
        },
    },
)
async def merge_notes(
    payload: MergeNotesRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(
            await service.merge_notes(
                owner_user_id=context.user.id,
                target_slug=payload.target_slug,
                source_slugs=payload.source_slugs,
                title=payload.title,
            )
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/notes/{note_slug}",
    response_model=AppNote,
    summary="Get note",
    description="Returns a single note, object, or collection by slug or by id (UUID).",
    responses={
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def get_note(
    note_slug: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(
            await service.get_note(owner_user_id=context.user.id, slug=note_slug)
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/notes/{note_slug}/restore",
    response_model=AppNote,
    summary="Restore deleted note",
    responses={
        200: {"description": "Restored note returned."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def restore_note(
    note_slug: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(
            await service.restore_note(owner_user_id=context.user.id, slug=note_slug)
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch(
    "/notes/{note_slug}",
    response_model=AppNote,
    summary="Update note",
    description="Updates mutable fields of a note: title, text and/or tags.",
    responses={
        200: {"description": "Updated note returned."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def update_note(
    note_slug: str,
    payload: UpdateNoteRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(
            await service.update_note(
                owner_user_id=context.user.id,
                slug=note_slug,
                title=payload.title,
                text=payload.text,
                tag_names=payload.tag_names,
            )
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/notes/{note_slug}/link-snapshots/decision",
    response_model=AppNote,
    summary="Confirm deferred link snapshot processing",
    description=(
        "Accepts or rejects snapshot processing for links that were left only in the "
        "text body after the automatic three-link limit."
    ),
    responses={
        200: {"description": "Updated note returned."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def decide_link_snapshots(
    note_slug: str,
    payload: LinkSnapshotDecisionRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(
            await service.decide_deferred_link_snapshots(
                owner_user_id=context.user.id,
                slug=note_slug,
                decision=payload.decision,
            )
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/notes/{note_slug}/download",
    summary="Download note archive",
    description="Downloads the note/object directory as a zip archive for native export flows.",
    responses={
        200: {"description": "Zip archive returned."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def download_note(
    note_slug: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> StreamingResponse:
    try:
        filename, body = await service.note_archive(owner_user_id=context.user.id, slug=note_slug)
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    return StreamingResponse(
        body,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(filename, "attachment"),
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/notes/{note_slug}/asset/{asset_id}",
    response_model=None,
    summary="Get asset file",
    description="Streams the raw file for a specific asset (image, document, etc.).",
    responses={
        200: {"description": "Asset file returned."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note or asset not found."},
    },
)
async def get_asset_file(
    note_slug: str,
    asset_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context_from_bearer_or_refresh_cookie)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> Response:
    try:
        asset_file = await service.get_asset_file(
            owner_user_id=context.user.id, slug=note_slug, asset_id=asset_id
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    await service.session.close()  # do not hold a DB connection while streaming
    return await storage_file_response(
        request,
        service.storage,
        key=asset_file.storage_key,
        filename=asset_file.filename,
        media_type=asset_file.mime_type,
        cache_control=MUTABLE_FILE_CACHE if asset_file.mutable else IMMUTABLE_FILE_CACHE,
    )


@router.get(
    "/notes/{note_slug}/asset/{asset_id}/thumbnail",
    summary="Get asset thumbnail",
    description=(
        "Returns the generated thumbnail artifact for an asset. Image and rendered document "
        "thumbnails are returned as JPEG. Returns 202 if thumbnail is not yet ready and "
        "204 if thumbnail generation is unsupported for this asset."
    ),
    responses={
        200: {"description": "Thumbnail artifact returned."},
        202: {"description": "Thumbnail not yet ready."},
        204: {"description": "Thumbnail is unavailable for this asset."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note or asset not found."},
    },
)
async def get_asset_thumbnail(
    note_slug: str,
    asset_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context_from_bearer_or_refresh_cookie)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> Response:
    try:
        thumbnail = await service.get_asset_thumbnail(
            owner_user_id=context.user.id, slug=note_slug, asset_id=asset_id
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    except ThumbnailUnavailableError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ThumbnailPendingError:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    await service.session.close()
    assert thumbnail.key is not None  # guaranteed by get_asset_thumbnail
    return await storage_file_response(
        request,
        service.storage,
        key=thumbnail.key,
        filename=thumbnail.filename,
        media_type=thumbnail.mime_type,
    )


@router.delete(
    "/notes/{note_slug}/items",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove items from collection",
    description="Detaches items from a collection without deleting the child notes.",
    responses={
        204: {"description": "Items removed from collection."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Collection not found."},
    },
)
async def remove_collection_items(
    note_slug: str,
    payload: RemoveCollectionItemsRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> Response:
    try:
        await service.remove_collection_items(
            owner_user_id=context.user.id,
            collection_slug=note_slug,
            item_slugs=payload.item_slugs,
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/notes/{note_slug}/favorite",
    response_model=AppNote,
    summary="Set note favorite state",
    description="Marks or unmarks a note, object, or collection as favorite.",
    responses={
        200: {"description": "Favorite state updated."},
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def set_note_favorite(
    note_slug: str,
    payload: FavoriteNoteRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(
            await service.set_favorite(
                owner_user_id=context.user.id,
                slug=note_slug,
                is_favorite=payload.is_favorite,
            )
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


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
    response_model=FolderDetailAppResponse,
    summary="Get folder detail",
    description="Returns a folder, notes inside it, and tags used by notes in that folder.",
    responses={
        401: {
            "model": ErrorResponse,
            "description": "Missing or invalid access token.",
        },
        404: {"model": ErrorResponse, "description": "Folder not found."},
    },
)
async def get_folder(
    folder_path: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> FolderDetailAppResponse:
    try:
        detail = await service.get_folder_detail(
            owner_user_id=context.user.id,
            folder_path=folder_path,
        )
        return FolderDetailAppResponse(
            folder=detail.folder,
            tags=detail.tags,
            notes=[note_card_to_app_note(n) for n in detail.notes],
        )
    except FolderNotFoundError as exc:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="folder_not_found",
            message="Folder not found.",
        ) from exc
