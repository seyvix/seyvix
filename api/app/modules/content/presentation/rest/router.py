from __future__ import annotations

from pathlib import Path
from typing import Annotated

from app.api.dependencies import get_db_session
from app.api.errors import AppError
from app.api.schemas import ErrorResponse
from app.modules.auth.presentation.rest.router import get_auth_context
from app.modules.auth.service import AuthContext
from app.modules.content.app_note import (
    AppNote,
    AppNoteListResponse,
    FileUploadAppResponse,
    FolderDetailAppResponse,
    note_card_to_app_note,
    upload_result_to_json_bytes,
)
from app.modules.content.schemas import (
    BulkDeleteRequest,
    CreateNoteRequest,
    FavoriteNoteRequest,
    FolderTreeResponse,
    MergeNotesRequest,
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
    UploadedContent,
)
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

router = APIRouter(tags=["content"])


def get_content_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ContentService:
    storage_root = getattr(request.app.state, "content_storage_root", Path("data/content"))
    storage_backend = getattr(request.app.state, "storage_backend", None)
    return ContentService(session, Path(storage_root), storage_backend=storage_backend)


def _not_found(exc: Exception) -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="note_not_found",
        message="Note not found.",
    )


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
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Uploaded file not found."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
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
            "description": "Temporary upload metadata or created object returned (camelCase App note when object is present).",
            "model": FileUploadAppResponse,
        },
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        422: {"model": ErrorResponse, "description": "Validation error in input payload."},
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

    uploaded_files = [
        UploadedContent(
            filename=f.filename or "file",
            content_type=f.content_type,
            data=await f.read(),
        )
        for f in files_to_upload
    ]
    result = await service.upload_files(
        owner_user_id=context.user.id,
        files=uploaded_files,
        title=title,
        folder_path=folder_path,
        tag_names=tag_names or [],
        create_or_attach_object=create_object or object_id is not None,
        object_id=object_id,
    )
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
    tags: Annotated[list[str] | None, Query()] = None,
    folder: Annotated[str | None, Query(max_length=1024)] = None,
    folders: Annotated[str | None, Query(max_length=1024)] = None,
    sort: Annotated[NoteSort, Query()] = "newest",
) -> AppNoteListResponse:
    lst = await service.list_notes(
        owner_user_id=context.user.id,
        search=search,
        tag_slugs=tags or [],
        folder_path=folders or folder,
        sort=sort,
    )
    return AppNoteListResponse(items=[note_card_to_app_note(n) for n in lst.items])


@router.delete(
    "/notes",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bulk delete notes",
    description="Permanently deletes the specified notes and their storage files.",
    responses={
        204: {"description": "Notes deleted."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
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
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "One or more notes were not found."},
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
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Note not found."},
    },
)
async def get_note(
    note_slug: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> AppNote:
    try:
        return note_card_to_app_note(await service.get_note(owner_user_id=context.user.id, slug=note_slug))
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch(
    "/notes/{note_slug}",
    response_model=AppNote,
    summary="Update note",
    description="Updates mutable fields of a note: title and/or tags.",
    responses={
        200: {"description": "Updated note returned."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
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
                tag_names=payload.tag_names,
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


@router.get(
    "/notes/{note_slug}/asset/{asset_id}",
    summary="Get asset file",
    description="Streams the raw file for a specific asset (image, document, etc.).",
    responses={
        200: {"description": "Asset file returned."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Note or asset not found."},
    },
)
async def get_asset_file(
    note_slug: str,
    asset_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> FileResponse:
    try:
        path, mime = await service.get_asset_file(
            owner_user_id=context.user.id, slug=note_slug, asset_id=asset_id
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    return FileResponse(path, media_type=mime)


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
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Note or asset not found."},
    },
)
async def get_asset_thumbnail(
    note_slug: str,
    asset_id: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ContentService, Depends(get_content_service)],
) -> Response:
    try:
        path, mime_type = await service.get_asset_thumbnail(
            owner_user_id=context.user.id, slug=note_slug, asset_id=asset_id
        )
    except NoteNotFoundError as exc:
        raise _not_found(exc) from exc
    except ThumbnailUnavailableError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ThumbnailPendingError:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return FileResponse(path, media_type=mime_type)


@router.delete(
    "/notes/{note_slug}/items",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove items from collection",
    description="Detaches items from a collection without deleting the child notes.",
    responses={
        204: {"description": "Items removed from collection."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
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
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
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
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
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
