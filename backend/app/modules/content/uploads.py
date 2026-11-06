"""Uploaded files: spooling multipart parts to disk, inspection and the pending-upload flow."""

from __future__ import annotations

import asyncio
import importlib
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.logging import get_logger
from app.modules.content.infrastructure.repositories import FileUploadRepository
from app.modules.content.models import ContentFileUpload
from app.modules.content.schemas import FileUploadResponse, UploadedFileResponse
from app.modules.content.text import image_dimensions_from_header, media_type_for
from app.platform.storage.keys import safe_file_name, upload_key
from app.platform.storage.service import StorageBackend, StoredObject

logger = get_logger(__name__)

SPOOL_CHUNK_BYTES = 1024 * 1024
IMAGE_HEADER_BYTES = 64 * 1024
MAX_TEXT_CONTENT_BYTES = 1024 * 1024
PENDING_UPLOAD_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class UploadedContent:
    """A file on local disk, owned by the caller (it is only read, never moved/deleted)."""

    filename: str
    content_type: str | None
    path: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FileFacts:
    media_type: str
    image_width: int | None
    image_height: int | None
    # Decoded UTF-8 body of text files (first MAX_TEXT_CONTENT_BYTES).
    text_content: str | None


@asynccontextmanager
async def spool_upload_files(
    files: Sequence[UploadFile], *, max_bytes: int
) -> AsyncIterator[list[UploadedContent]]:
    """Copy multipart parts to a private temporary directory in bounded chunks.

    Raises `AppError(413)` when a file exceeds `max_bytes`. Everything is removed on exit,
    including when the request is aborted.
    """
    with tempfile.TemporaryDirectory(prefix="seyvix-upload-") as directory:
        spooled: list[UploadedContent] = []
        for index, upload in enumerate(files):
            filename = (upload.filename or "file").strip() or "file"
            path = Path(directory) / f"{index}-{safe_file_name(filename)}"
            size = await _spool(upload, path, max_bytes=max_bytes, filename=filename)
            spooled.append(
                UploadedContent(
                    filename=filename[:512],
                    content_type=upload.content_type,
                    path=path,
                    size_bytes=size,
                )
            )
        yield spooled


async def _spool(upload: UploadFile, path: Path, *, max_bytes: int, filename: str) -> int:
    size = 0
    handle = await asyncio.to_thread(path.open, "wb")
    try:
        while chunk := await upload.read(SPOOL_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise AppError(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    code="file_too_large",
                    message=f"File is larger than {max_bytes} bytes.",
                    details=[{"filename": filename, "max_bytes": max_bytes}],
                )
            await asyncio.to_thread(handle.write, chunk)
    finally:
        await asyncio.to_thread(handle.close)
        await upload.close()
    return size


async def inspect_file(uploaded: UploadedContent) -> FileFacts:
    media_type = media_type_for(uploaded.filename, uploaded.content_type)
    width: int | None = None
    height: int | None = None
    text_content: str | None = None
    if media_type == "image":
        width, height = await asyncio.to_thread(_image_dimensions, uploaded)
    elif media_type == "text":
        text_content = await asyncio.to_thread(_read_text, uploaded.path)
    return FileFacts(
        media_type=media_type, image_width=width, image_height=height, text_content=text_content
    )


def _read_text(path: Path) -> str | None:
    with path.open("rb") as handle:
        data = handle.read(MAX_TEXT_CONTENT_BYTES + 1)
    truncated = len(data) > MAX_TEXT_CONTENT_BYTES
    try:
        errors = "ignore" if truncated else "strict"
        return data[:MAX_TEXT_CONTENT_BYTES].decode("utf-8", errors=errors)
    except UnicodeDecodeError:
        return None


def _image_dimensions(uploaded: UploadedContent) -> tuple[int | None, int | None]:
    with uploaded.path.open("rb") as handle:
        header = handle.read(IMAGE_HEADER_BYTES)
    dimensions = image_dimensions_from_header(header)
    if dimensions is not None:
        return dimensions
    # Rare formats (HEIC, BMP, TIFF...): let PyMuPDF parse the file from disk.
    try:
        fitz: Any = importlib.import_module("fitz")
        document: Any = fitz.open(str(uploaded.path))
    except Exception:  # noqa: BLE001 - optional dependency / unparseable image
        logger.info("content.image_dimensions_unavailable", filename=uploaded.filename)
        return None, None
    try:
        if document.page_count == 0:
            return None, None
        rect = document[0].rect
        width, height = int(rect.width), int(rect.height)
        return (width, height) if width > 0 and height > 0 else (None, None)
    except Exception:  # noqa: BLE001 - corrupt image
        logger.info("content.image_dimensions_unavailable", filename=uploaded.filename)
        return None, None
    finally:
        document.close()


class StorageWrites:
    """Storage side effects of one DB transaction, undone (best effort) if it fails."""

    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage
        self._undo: list[Callable[[], Awaitable[None]]] = []

    async def put_file(self, key: str, path: Path, content_type: str | None) -> StoredObject:
        stored = await self.storage.put_file(key, path, content_type)
        self._undo.append(lambda: self.storage.delete(key))
        return stored

    async def put_bytes(self, key: str, data: bytes, content_type: str | None) -> StoredObject:
        stored = await self.storage.put_bytes(key, data, content_type)
        self._undo.append(lambda: self.storage.delete(key))
        return stored

    async def move(self, source_key: str, target_key: str) -> None:
        await self.storage.move(source_key, target_key)
        self._undo.append(lambda: self.storage.move(target_key, source_key))

    async def rollback(self) -> None:
        for undo in reversed(self._undo):
            try:
                await undo()
            except Exception:  # noqa: BLE001 - leftovers are removed by the orphan sweep
                logger.warning("content.storage.rollback_failed", exc_info=True)
        self._undo.clear()

    def commit(self) -> None:
        self._undo.clear()


@asynccontextmanager
async def storage_transaction(
    session: AsyncSession, storage: StorageBackend
) -> AsyncIterator[StorageWrites]:
    """Write files, then let the caller commit the session inside the block. If anything
    raises, the session is rolled back and written files are deleted / moved back."""
    writes = StorageWrites(storage)
    try:
        yield writes
    except BaseException:
        await session.rollback()
        await writes.rollback()
        raise
    writes.commit()


class PendingUploads:
    """Two-step upload: files are stored under `uploads/{owner}/{id}/` and later consumed by
    note creation (moved into the note's prefix) or removed by maintenance after expiry."""

    def __init__(self, session: AsyncSession, storage: StorageBackend) -> None:
        self.session = session
        self.storage = storage
        self.repository = FileUploadRepository(session)

    async def create(
        self, *, owner_user_id: str, files: Sequence[UploadedContent]
    ) -> FileUploadResponse:
        expires_at = datetime.now(UTC) + PENDING_UPLOAD_TTL
        uploads: list[ContentFileUpload] = []
        async with storage_transaction(self.session, self.storage) as writes:
            for uploaded in files:
                upload_id = str(uuid4())
                facts = await inspect_file(uploaded)
                key = upload_key(owner_user_id, upload_id, uploaded.filename)
                stored = await writes.put_file(key, uploaded.path, uploaded.content_type)
                upload = ContentFileUpload(
                    id=upload_id,
                    owner_user_id=owner_user_id,
                    source_filename=uploaded.filename,
                    mime_type=uploaded.content_type,
                    media_type=facts.media_type,
                    size_bytes=stored.size_bytes,
                    storage_key=key,
                    checksum=stored.checksum,
                    image_width=facts.image_width,
                    image_height=facts.image_height,
                    text_content=facts.text_content,
                    expires_at=expires_at,
                )
                self.repository.add(upload)
                uploads.append(upload)
            await self.session.commit()
        return FileUploadResponse(
            files=[
                UploadedFileResponse(
                    id=upload.id,
                    source_filename=upload.source_filename,
                    media_type=upload.media_type,  # type: ignore[arg-type]
                    mime_type=upload.mime_type,
                    size_bytes=upload.size_bytes,
                    expires_at=upload.expires_at,
                )
                for upload in uploads
            ],
            object=None,
        )

    async def take(
        self, *, owner_user_id: str, upload_ids: Sequence[str]
    ) -> list[ContentFileUpload]:
        """Lock the requested, unexpired uploads (in request order). Missing ids → empty list."""
        unique_ids = list(dict.fromkeys(upload_ids))
        rows = await self.repository.list_available(
            owner_user_id=owner_user_id, upload_ids=unique_ids, now=datetime.now(UTC)
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(unique_ids):
            return []
        return [by_id[upload_id] for upload_id in unique_ids]
