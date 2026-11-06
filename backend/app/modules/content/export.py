"""Streaming zip export of a note: `manifest.json` plus every asset (children in folders).

The archive is produced on the fly in bounded chunks (no temp files, no full in-memory
build), so an aborted download simply stops the generator.
"""

from __future__ import annotations

import asyncio
import json
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import IO, Any, cast

from app.core.logging import get_logger
from app.modules.content.cards import visible_children
from app.modules.content.models import ContentObject
from app.modules.content.text import media_type_for
from app.platform.storage.keys import safe_file_name
from app.platform.storage.service import StorageBackend, StorageObjectNotFoundError

logger = get_logger(__name__)

# Already-compressed media is stored as is; deflating it only burns CPU.
_STORED_MEDIA = frozenset({"image", "audio", "video"})


class _ChunkSink:
    """Write-only, non-seekable file object collecting zip output between yields."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._chunks.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        return None

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


@dataclass(frozen=True, slots=True)
class _Entry:
    name: str
    storage_key: str
    compress: bool


def build_manifest(
    content_object: ContentObject,
    *,
    folders: dict[str, str],
    tags: dict[str, list[str]],
) -> dict[str, Any]:
    children = visible_children(content_object)
    return {
        "id": content_object.id,
        "slug": content_object.slug,
        "kind": content_object.kind,
        "media_type": content_object.media_type,
        "title": content_object.title,
        "source_filename": content_object.source_filename,
        "folder": folders.get(content_object.id),
        "tags": tags.get(content_object.id, []),
        "created_at": content_object.created_at.isoformat(),
        "updated_at": content_object.updated_at.isoformat(),
        "assets": [
            {"id": asset.id, "role": asset.role, "filename": asset.filename}
            for asset in content_object.assets
        ],
        "items": [build_manifest(child, folders=folders, tags=tags) for child in children],
    }


def _unique_name(name: str, used: set[str]) -> str:
    candidate = name
    path = PurePosixPath(name)
    counter = 2
    while candidate.casefold() in used:
        candidate = str(path.with_name(f"{path.stem} ({counter}){path.suffix}"))
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _entries(content_object: ContentObject) -> list[_Entry]:
    used = {"manifest.json"}
    entries: list[_Entry] = []

    def visit(obj: ContentObject, folder: str) -> None:
        for asset in obj.assets:
            name = _unique_name(f"{folder}{safe_file_name(asset.filename)}", used)
            compress = media_type_for(asset.filename, asset.mime_type) not in _STORED_MEDIA
            entries.append(_Entry(name=name, storage_key=asset.storage_key, compress=compress))
        for child in visible_children(obj):
            child_folder = _unique_name(f"{folder}{safe_file_name(child.slug)}/", used)
            visit(child, child_folder)

    visit(content_object, "")
    return entries


async def stream_note_archive(
    storage: StorageBackend, content_object: ContentObject, manifest: dict[str, Any]
) -> AsyncIterator[bytes]:
    """Requires the note tree loaded (assets and children) before streaming starts."""
    entries = _entries(content_object)
    sink = _ChunkSink()
    archive = zipfile.ZipFile(cast(IO[bytes], sink), mode="w", allowZip64=True)
    try:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        archive.writestr(
            zipfile.ZipInfo("manifest.json"), manifest_bytes, compress_type=zipfile.ZIP_DEFLATED
        )
        yield sink.drain()
        for entry in entries:
            info = zipfile.ZipInfo(entry.name)
            info.compress_type = zipfile.ZIP_DEFLATED if entry.compress else zipfile.ZIP_STORED
            try:
                with archive.open(info, mode="w", force_zip64=True) as target:
                    async for chunk in storage.iter_bytes(entry.storage_key):
                        if entry.compress:
                            await asyncio.to_thread(target.write, chunk)
                        else:
                            target.write(chunk)
                        if data := sink.drain():
                            yield data
            except StorageObjectNotFoundError:
                logger.warning("content.export.asset_missing", key=entry.storage_key)
            yield sink.drain()
        archive.close()
        yield sink.drain()
    finally:
        if archive.fp is not None:
            archive.close()
