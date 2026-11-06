from __future__ import annotations

import asyncio
import hashlib
import io
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal
from urllib.parse import urlparse

import urllib3
from minio import Minio
from minio.commonconfig import CopySource
from minio.deleteobjects import DeleteObject
from minio.error import S3Error

from app.core.logging import get_logger
from app.platform.storage.service import (
    DEFAULT_CHUNK_SIZE,
    StorageError,
    StorageObjectInfo,
    StorageObjectNotFoundError,
    StoredObject,
    validate_key,
    validate_prefix,
)

logger = get_logger(__name__)

_NOT_FOUND_CODES = {"NoSuchKey", "NoSuchObject", "NotFound", "ResourceNotFound"}
# Multipart part size; with one upload thread memory stays bounded to about one part.
_PART_SIZE = 8 * 1024 * 1024
_DELETE_BATCH = 1000
_READY_TIMEOUT_SECONDS = 5.0


class _HashingReader(io.RawIOBase):
    """File wrapper that hashes bytes as minio reads them (single pass over the file)."""

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size)
        self.digest.update(chunk)
        return chunk


class S3Storage:
    """S3-compatible storage. The minio client is synchronous, so every call runs in a
    worker thread; large transfers are streamed in bounded chunks."""

    name: Literal["local", "s3"] = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str | None,
    ) -> None:
        parsed = urlparse(endpoint_url)
        self.bucket = bucket
        self._client = Minio(
            endpoint=parsed.netloc or parsed.path,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
            region=region,
            http_client=urllib3.PoolManager(
                maxsize=16,
                timeout=urllib3.Timeout(connect=5.0, read=120.0),
                retries=urllib3.Retry(
                    total=3, backoff_factor=0.3, status_forcelist=(502, 503, 504)
                ),
            ),
        )
        self._bucket_ready = False
        self._bucket_lock = asyncio.Lock()

    def local_path(self, key: str) -> Path | None:
        return None

    async def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        async with self._bucket_lock:
            if self._bucket_ready:
                return
            exists = await asyncio.to_thread(self._client.bucket_exists, self.bucket)
            if not exists:
                await asyncio.to_thread(self._client.make_bucket, self.bucket)
            self._bucket_ready = True

    async def put_file(self, key: str, path: Path, content_type: str | None = None) -> StoredObject:
        validate_key(key)
        await self._ensure_bucket()
        size, checksum = await asyncio.to_thread(self._put_file_sync, key, path, content_type)
        return StoredObject(key=key, size_bytes=size, checksum=checksum, content_type=content_type)

    def _put_file_sync(self, key: str, path: Path, content_type: str | None) -> tuple[int, str]:
        size = path.stat().st_size
        with path.open("rb") as handle:
            reader = _HashingReader(handle)
            self._client.put_object(
                self.bucket,
                key,
                reader,  # type: ignore[arg-type]
                length=size,
                content_type=content_type or "application/octet-stream",
                part_size=_PART_SIZE,
                num_parallel_uploads=1,
            )
        return size, f"sha256:{reader.digest.hexdigest()}"

    async def put_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> StoredObject:
        validate_key(key)
        await self._ensure_bucket()
        await asyncio.to_thread(
            self._client.put_object,
            self.bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type or "application/octet-stream",
        )
        return StoredObject(
            key=key,
            size_bytes=len(data),
            checksum=f"sha256:{hashlib.sha256(data).hexdigest()}",
            content_type=content_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        validate_key(key)
        return await asyncio.to_thread(self._get_bytes_sync, key)

    def _get_bytes_sync(self, key: str) -> bytes:
        response = self._call(self._client.get_object, self.bucket, key, key=key)
        try:
            return bytes(response.read())
        finally:
            response.close()
            response.release_conn()

    async def iter_bytes(
        self,
        key: str,
        offset: int = 0,
        length: int | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        validate_key(key)
        response = await asyncio.to_thread(
            self._call, self._client.get_object, self.bucket, key, offset, length or 0, key=key
        )
        try:
            stream: Iterator[bytes] = response.stream(chunk_size)
            while True:
                chunk = await asyncio.to_thread(next, stream, None)
                if chunk is None:
                    break
                yield chunk
        finally:
            response.close()
            response.release_conn()

    async def stat(self, key: str) -> StorageObjectInfo:
        validate_key(key)
        result = await asyncio.to_thread(
            self._call, self._client.stat_object, self.bucket, key, key=key
        )
        modified = result.last_modified or datetime.now(UTC)
        return StorageObjectInfo(
            key=key,
            size_bytes=int(result.size or 0),
            content_type=result.content_type,
            modified_at=modified,
            etag=(result.etag or "").strip('"') or f"{result.size:x}",
        )

    async def exists(self, key: str) -> bool:
        try:
            await self.stat(key)
        except StorageObjectNotFoundError:
            return False
        return True

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(self._client.remove_object, self.bucket, key)

    async def move(self, source_key: str, target_key: str) -> None:
        validate_key(source_key)
        validate_key(target_key)
        await asyncio.to_thread(
            self._call,
            self._client.copy_object,
            self.bucket,
            target_key,
            CopySource(self.bucket, source_key),
            key=source_key,
        )
        await asyncio.to_thread(self._client.remove_object, self.bucket, source_key)

    async def delete_prefix(self, prefix: str) -> int:
        validate_prefix(prefix)
        return await asyncio.to_thread(self._delete_prefix_sync, prefix)

    def _delete_prefix_sync(self, prefix: str) -> int:
        deleted = 0
        batch: list[DeleteObject] = []
        for item in self._client.list_objects(self.bucket, prefix=prefix, recursive=True):
            if item.object_name is None:
                continue
            batch.append(DeleteObject(item.object_name))
            if len(batch) >= _DELETE_BATCH:
                deleted += self._remove_batch(batch)
                batch = []
        if batch:
            deleted += self._remove_batch(batch)
        return deleted

    def _remove_batch(self, batch: list[DeleteObject]) -> int:
        errors = list(self._client.remove_objects(self.bucket, batch))
        for error in errors:
            logger.warning("storage.s3.delete_failed", key=error.name, code=error.code)
        if errors:
            raise StorageError(f"failed to delete {len(errors)} objects")
        return len(batch)

    async def list_prefixes(self, prefix: str) -> list[str]:
        validate_prefix(prefix)
        return await asyncio.to_thread(self._list_prefixes_sync, prefix)

    def _list_prefixes_sync(self, prefix: str) -> list[str]:
        names: list[str] = []
        for item in self._client.list_objects(self.bucket, prefix=prefix, recursive=False):
            if item.is_dir and item.object_name:
                names.append(item.object_name[len(prefix) :].rstrip("/"))
        return names

    async def prefix_modified_at(self, prefix: str) -> datetime | None:
        validate_prefix(prefix)
        return await asyncio.to_thread(self._prefix_modified_sync, prefix)

    def _prefix_modified_sync(self, prefix: str) -> datetime | None:
        newest: datetime | None = None
        for item in self._client.list_objects(self.bucket, prefix=prefix, recursive=True):
            if item.last_modified is not None and (newest is None or item.last_modified > newest):
                newest = item.last_modified
        return newest

    async def download_to(self, key: str, path: Path) -> None:
        validate_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            self._call, self._client.fget_object, self.bucket, key, str(path), key=key
        )

    async def is_ready(self) -> bool:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._client.bucket_exists, self.bucket),
                timeout=_READY_TIMEOUT_SECONDS,
            )
        except (TimeoutError, S3Error, urllib3.exceptions.HTTPError) as exc:
            logger.warning("storage.s3.not_ready", error=str(exc))
            return False

    @staticmethod
    def _call(function: Any, *args: Any, key: str) -> Any:
        try:
            return function(*args)
        except S3Error as exc:
            if exc.code in _NOT_FOUND_CODES:
                raise StorageObjectNotFoundError(key) from exc
            raise
