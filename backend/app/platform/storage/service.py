from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from unicodedata import normalize
from urllib.parse import urlparse

from minio import Minio


@dataclass(slots=True)
class StoredObject:
    storage_backend: str
    bucket: str
    storage_key: str
    storage_ref: str
    content_type: str | None
    size_bytes: int
    checksum: str


@dataclass(slots=True)
class StorageObjectInfo:
    size_bytes: int
    content_type: str | None


class StorageBackend(Protocol):
    bucket: str

    def put_bytes(
        self,
        *,
        storage_key: str,
        data: bytes,
        content_type: str | None,
    ) -> StoredObject: ...

    def get_bytes(self, storage_key: str) -> bytes: ...

    def stat_object(self, storage_key: str) -> StorageObjectInfo: ...

    def iter_object_bytes(
        self,
        storage_key: str,
        *,
        offset: int = 0,
        length: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]: ...

    def delete_object(self, storage_key: str) -> None: ...


class StorageKeyBuilder:
    @staticmethod
    def content_asset_original(
        *,
        content_object_id: str,
        asset_id: str,
        filename: str,
    ) -> str:
        suffix = Path(filename).suffix.lower()
        if not suffix:
            suffix = ".bin"
        return f"content-assets/{content_object_id}/{asset_id}/original{suffix}"

    @staticmethod
    def pending_upload(*, owner_user_id: str, upload_id: str, filename: str) -> str:
        return f"pending-uploads/{owner_user_id}/{upload_id}/{_safe_file_name(filename)}"

    @staticmethod
    def content_manifest(*, content_object_id: str) -> str:
        return f"content-assets/{content_object_id}/manifest.json"

    @staticmethod
    def snapshot_artifact(
        *,
        content_object_id: str,
        snapshot_id: str,
        filename: str,
    ) -> str:
        return f"snapshots/{content_object_id}/{snapshot_id}/{_safe_file_name(filename)}"

    @staticmethod
    def snapshot_artifact_resource(
        *,
        content_object_id: str,
        snapshot_id: str,
        filename: str,
    ) -> str:
        return f"snapshots/{content_object_id}/{snapshot_id}/resources/{_safe_file_name(filename)}"

    @staticmethod
    def snapshot_artifact_manifest(
        *,
        content_object_id: str,
        snapshot_id: str,
    ) -> str:
        return f"snapshots/{content_object_id}/{snapshot_id}/manifest.json"


class LocalVolumeStorage:
    def __init__(self, *, root: Path, bucket: str) -> None:
        self.root = root
        self.bucket = bucket
        self.storage_backend = "local"

    def put_bytes(
        self,
        *,
        storage_key: str,
        data: bytes,
        content_type: str | None,
    ) -> StoredObject:
        path = self.root / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(
            storage_backend=self.storage_backend,
            bucket=self.bucket,
            storage_key=storage_key,
            storage_ref=self.storage_ref(storage_key),
            content_type=content_type,
            size_bytes=len(data),
            checksum=_sha256(data),
        )

    def get_bytes(self, storage_key: str) -> bytes:
        return (self.root / storage_key).read_bytes()

    def stat_object(self, storage_key: str) -> StorageObjectInfo:
        path = self.root / storage_key
        return StorageObjectInfo(size_bytes=path.stat().st_size, content_type=None)

    def iter_object_bytes(
        self,
        storage_key: str,
        *,
        offset: int = 0,
        length: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        remaining = length
        with (self.root / storage_key).open("rb") as file:
            file.seek(offset)
            while remaining is None or remaining > 0:
                read_size = chunk_size if remaining is None else min(chunk_size, remaining)
                chunk = file.read(read_size)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk

    def delete_object(self, storage_key: str) -> None:
        path = self.root / storage_key
        if path.exists():
            path.unlink()

    def storage_ref(self, storage_key: str) -> str:
        return f"s3://{self.bucket}/{storage_key}"


class S3CompatibleStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str | None,
        secure: bool | None = None,
    ) -> None:
        parsed = urlparse(endpoint_url)
        if secure is None:
            secure = parsed.scheme == "https"
        endpoint = parsed.netloc or parsed.path
        self.bucket = bucket
        self.storage_backend = "s3"
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )

    def put_bytes(
        self,
        *,
        storage_key: str,
        data: bytes,
        content_type: str | None,
    ) -> StoredObject:
        from io import BytesIO

        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self.client.put_object(
            self.bucket,
            storage_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return StoredObject(
            storage_backend=self.storage_backend,
            bucket=self.bucket,
            storage_key=storage_key,
            storage_ref=f"s3://{self.bucket}/{storage_key}",
            content_type=content_type,
            size_bytes=len(data),
            checksum=_sha256(data),
        )

    def get_bytes(self, storage_key: str) -> bytes:
        response = self.client.get_object(self.bucket, storage_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def stat_object(self, storage_key: str) -> StorageObjectInfo:
        stat = self.client.stat_object(self.bucket, storage_key)
        return StorageObjectInfo(size_bytes=stat.size, content_type=stat.content_type)

    def iter_object_bytes(
        self,
        storage_key: str,
        *,
        offset: int = 0,
        length: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        response = self.client.get_object(
            self.bucket,
            storage_key,
            offset=offset,
            length=length,
        )
        try:
            yield from response.stream(chunk_size)
        finally:
            response.close()
            response.release_conn()

    def delete_object(self, storage_key: str) -> None:
        self.client.remove_object(self.bucket, storage_key)


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _safe_file_name(value: str) -> str:
    normalized = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", normalized).strip(".-")
    return normalized or "file"
