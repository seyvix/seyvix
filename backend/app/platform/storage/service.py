"""Object storage abstraction shared by the API and every worker.

All methods are async and streaming-first: large payloads move between disk and the backend
in fixed-size chunks and are never held in memory. Keys are relative, `/`-separated paths
(see `app.platform.storage.keys` for the layout).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

DEFAULT_CHUNK_SIZE = 256 * 1024


class StorageError(Exception):
    """Base class for storage failures."""


class StorageObjectNotFoundError(StorageError, FileNotFoundError):
    """The requested key does not exist."""


class InvalidStorageKeyError(StorageError, ValueError):
    """The key is empty, absolute or escapes the storage root."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    # "sha256:<hex>" computed while the payload was streamed to the backend.
    checksum: str
    content_type: str | None


@dataclass(frozen=True, slots=True)
class StorageObjectInfo:
    key: str
    size_bytes: int
    content_type: str | None
    modified_at: datetime
    etag: str


class StorageBackend(Protocol):
    name: Literal["local", "s3"]

    async def put_file(self, key: str, path: Path, content_type: str | None = None) -> StoredObject:
        """Stream a local file to `key` (overwrites). The source file is left untouched."""
        ...

    async def put_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> StoredObject:
        """Store a small payload (manifests, short text). Use `put_file` for anything large."""
        ...

    async def get_bytes(self, key: str) -> bytes:
        """Read a small object fully. Raises `StorageObjectNotFoundError`."""
        ...

    def iter_bytes(
        self,
        key: str,
        offset: int = 0,
        length: int | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """Stream `length` bytes (or until EOF) starting at `offset`.
        Raises `StorageObjectNotFoundError` on first iteration if the key is missing."""
        ...

    async def stat(self, key: str) -> StorageObjectInfo:
        """Raises `StorageObjectNotFoundError`."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None:
        """Delete one object; missing keys are ignored."""
        ...

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `prefix` (must end with `/`). Returns the count."""
        ...

    async def move(self, source_key: str, target_key: str) -> None:
        """Rename an object (atomic on the local backend, server-side copy on S3).
        Raises `StorageObjectNotFoundError` when the source is missing."""
        ...

    async def list_prefixes(self, prefix: str) -> list[str]:
        """Names of the immediate child "directories" under `prefix` (must end with `/`)."""
        ...

    async def prefix_modified_at(self, prefix: str) -> datetime | None:
        """Newest modification time of any object under `prefix`; None when empty."""
        ...

    def local_path(self, key: str) -> Path | None:
        """Filesystem path of `key` for the local backend (None for remote backends).
        The file may not exist; check with `exists`/`stat`."""
        ...

    async def download_to(self, key: str, path: Path) -> None:
        """Copy the object to a local file (streams; creates parent directories)."""
        ...

    async def is_ready(self) -> bool: ...


def validate_key(key: str) -> str:
    """Reject keys that could escape the storage root or address a directory."""
    if not key or key.startswith("/") or key.endswith("/") or "\\" in key or "\x00" in key:
        raise InvalidStorageKeyError(key)
    if any(part in {"", ".", ".."} for part in key.split("/")):
        raise InvalidStorageKeyError(key)
    return key


def validate_prefix(prefix: str) -> str:
    if not prefix.endswith("/"):
        raise InvalidStorageKeyError(f"prefix must end with '/': {prefix!r}")
    validate_key(prefix[:-1])
    return prefix
