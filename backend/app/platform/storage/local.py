from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Literal

from app.platform.storage.service import (
    DEFAULT_CHUNK_SIZE,
    StorageObjectInfo,
    StorageObjectNotFoundError,
    StoredObject,
    validate_key,
    validate_prefix,
)

_COPY_CHUNK = 1024 * 1024


class LocalVolumeStorage:
    """Filesystem storage rooted at `root` (a volume shared by api and workers).

    Writes are atomic (temp file in the target directory + `os.replace`), so readers never
    observe partial files. Blocking filesystem calls run in worker threads.
    """

    name: Literal["local", "s3"] = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*validate_key(key).split("/"))

    def _prefix_path(self, prefix: str) -> Path:
        return self.root.joinpath(*validate_prefix(prefix)[:-1].split("/"))

    def local_path(self, key: str) -> Path | None:
        return self._path(key)

    async def put_file(self, key: str, path: Path, content_type: str | None = None) -> StoredObject:
        target = self._path(key)
        size, checksum = await asyncio.to_thread(self._write_atomic_from_file, target, path)
        return StoredObject(key=key, size_bytes=size, checksum=checksum, content_type=content_type)

    async def put_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> StoredObject:
        target = self._path(key)
        await asyncio.to_thread(self._write_atomic_bytes, target, data)
        return StoredObject(
            key=key,
            size_bytes=len(data),
            checksum=f"sha256:{hashlib.sha256(data).hexdigest()}",
            content_type=content_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
            raise StorageObjectNotFoundError(key) from exc

    async def iter_bytes(
        self,
        key: str,
        offset: int = 0,
        length: int | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        path = self._path(key)
        try:
            handle: BinaryIO = await asyncio.to_thread(path.open, "rb")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
            raise StorageObjectNotFoundError(key) from exc
        try:
            if offset:
                await asyncio.to_thread(handle.seek, offset)
            remaining = length
            while remaining is None or remaining > 0:
                size = chunk_size if remaining is None else min(chunk_size, remaining)
                chunk = await asyncio.to_thread(handle.read, size)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def stat(self, key: str) -> StorageObjectInfo:
        path = self._path(key)
        try:
            result = await asyncio.to_thread(path.stat)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise StorageObjectNotFoundError(key) from exc
        if not path.is_file():
            raise StorageObjectNotFoundError(key)
        return StorageObjectInfo(
            key=key,
            size_bytes=result.st_size,
            content_type=None,
            modified_at=datetime.fromtimestamp(result.st_mtime, UTC),
            etag=f"{result.st_size:x}-{result.st_mtime_ns:x}",
        )

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(self._delete_file, path)

    async def delete_prefix(self, prefix: str) -> int:
        directory = self._prefix_path(prefix)
        return await asyncio.to_thread(self._delete_tree, directory)

    async def move(self, source_key: str, target_key: str) -> None:
        source = self._path(source_key)
        target = self._path(target_key)
        try:
            await asyncio.to_thread(self._move_file, source, target)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise StorageObjectNotFoundError(source_key) from exc

    async def list_prefixes(self, prefix: str) -> list[str]:
        directory = self._prefix_path(prefix)
        return await asyncio.to_thread(self._list_dirs, directory)

    async def prefix_modified_at(self, prefix: str) -> datetime | None:
        directory = self._prefix_path(prefix)
        return await asyncio.to_thread(self._newest_mtime, directory)

    async def download_to(self, key: str, path: Path) -> None:
        source = self._path(key)
        try:
            await asyncio.to_thread(self._copy_file, source, path)
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
            raise StorageObjectNotFoundError(key) from exc

    async def is_ready(self) -> bool:
        return await asyncio.to_thread(self._check_writable)

    # --- blocking helpers (run in threads) ---------------------------------------------

    def _write_atomic_from_file(self, target: Path, source: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out, source.open("rb") as src:
                while chunk := src.read(_COPY_CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return size, f"sha256:{digest.hexdigest()}"

    def _write_atomic_bytes(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def _delete_file(self, path: Path) -> None:
        try:
            path.unlink()
        except (FileNotFoundError, NotADirectoryError):
            return
        self._prune_empty_parents(path.parent)

    def _delete_tree(self, directory: Path) -> int:
        if not directory.is_dir():
            return 0
        count = sum(len(files) for _, _, files in os.walk(directory))
        shutil.rmtree(directory)
        self._prune_empty_parents(directory.parent)
        return count

    def _prune_empty_parents(self, directory: Path) -> None:
        while directory != self.root and self.root in directory.parents:
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    def _list_dirs(self, directory: Path) -> list[str]:
        try:
            with os.scandir(directory) as entries:
                return [
                    entry.name
                    for entry in entries
                    if entry.is_dir(follow_symlinks=False) and not entry.name.startswith(".")
                ]
        except (FileNotFoundError, NotADirectoryError):
            return []

    def _move_file(self, source: Path, target: Path) -> None:
        if not source.is_file():
            raise FileNotFoundError(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        self._prune_empty_parents(source.parent)

    def _newest_mtime(self, directory: Path) -> datetime | None:
        newest: float | None = None
        for current, _, files in os.walk(directory):
            for name in files:
                try:
                    mtime = os.stat(os.path.join(current, name)).st_mtime
                except FileNotFoundError:
                    continue
                newest = mtime if newest is None else max(newest, mtime)
        return datetime.fromtimestamp(newest, UTC) if newest is not None else None

    def _copy_file(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def _check_writable(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=self.root):
                pass
        except OSError:
            return False
        return True
