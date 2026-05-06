from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from unicodedata import normalize

from app.modules.content.models import ContentObject
from app.platform.storage.service import LocalVolumeStorage, StorageBackend, StorageKeyBuilder


@dataclass(slots=True)
class StoredFile:
    filename: str
    relative_path: str
    size_bytes: int
    storage_backend: str
    bucket: str
    storage_key: str
    storage_ref: str
    checksum: str
    content_type: str | None = None


class ContentStorage:
    def __init__(self, root: Path, backend: StorageBackend | None = None) -> None:
        self.root = root
        self.backend = backend or LocalVolumeStorage(root=root, bucket="app-storage")

    def object_directory(
        self,
        *,
        owner_user_id: str,
        folder_path: str | None,
        slug: str,
        kind: str,
    ) -> Path:
        suffix = "collection" if kind == "collection" else "object"
        path = self.root / owner_user_id
        if folder_path:
            for segment in folder_path.split("/"):
                path = path / segment
        return path / f"{slug}.{suffix}"

    def write_text_object(
        self,
        *,
        content_object_id: str,
        asset_id: str,
        title: str,
        text: str,
    ) -> StoredFile:
        filename = "content.md"
        content = f"# {title}\n\n{text}\n"
        storage_key = StorageKeyBuilder.content_asset_original(
            content_object_id=content_object_id,
            asset_id=asset_id,
            filename=filename,
        )
        stored = self.backend.put_bytes(
            storage_key=storage_key,
            data=content.encode("utf-8"),
            content_type="text/markdown",
        )
        return self._stored_file(
            filename=filename,
            stored=stored,
        )

    def write_binary_object(
        self,
        *,
        content_object_id: str,
        asset_id: str,
        filename: str,
        data: bytes,
        content_type: str | None,
    ) -> StoredFile:
        storage_key = StorageKeyBuilder.content_asset_original(
            content_object_id=content_object_id,
            asset_id=asset_id,
            filename=filename,
        )
        stored = self.backend.put_bytes(
            storage_key=storage_key,
            data=data,
            content_type=content_type,
        )
        return self._stored_file(
            filename=filename,
            stored=stored,
        )

    def write_temp_file(
        self,
        *,
        owner_user_id: str,
        upload_id: str,
        filename: str,
        data: bytes,
    ) -> StoredFile:
        storage_key = StorageKeyBuilder.pending_upload(
            owner_user_id=owner_user_id,
            upload_id=upload_id,
            filename=filename,
        )
        stored = self.backend.put_bytes(
            storage_key=storage_key,
            data=data,
            content_type=None,
        )
        return self._stored_file(
            filename=filename,
            stored=stored,
        )

    def read_relative_file(self, relative_path: str) -> bytes:
        return self.backend.get_bytes(relative_path)

    def write_manifest(self, *, content_object_id: str, manifest: dict[str, object]) -> None:
        storage_key = StorageKeyBuilder.content_manifest(content_object_id=content_object_id)
        self.backend.put_bytes(
            storage_key=storage_key,
            data=json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            content_type="application/json",
        )

    def build_archive(self, content_object: ContentObject) -> Path:
        temp_file = NamedTemporaryFile(
            prefix=f"{content_object.slug}-",
            suffix=".zip",
            delete=False,
        )
        temp_file.close()
        archive_path = Path(temp_file.name)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            manifest_key = StorageKeyBuilder.content_manifest(content_object_id=content_object.id)
            try:
                archive.writestr("manifest.json", self.backend.get_bytes(manifest_key))
            except FileNotFoundError:
                archive.writestr("manifest.json", "{}")
            for asset in content_object.assets:
                try:
                    archive.writestr(asset.filename, self.backend.get_bytes(asset.storage_path))
                except FileNotFoundError:
                    continue
        return archive_path

    def remove_directory(self, content_object: ContentObject) -> None:
        for asset in content_object.assets:
            self.backend.delete_object(asset.storage_path)

    def remove_relative_file_parent(self, relative_path: str) -> None:
        self.backend.delete_object(relative_path)

    @staticmethod
    def _stored_file(*, filename: str, stored: Any) -> StoredFile:
        return StoredFile(
            filename=filename,
            relative_path=stored.storage_key,
            size_bytes=stored.size_bytes,
            storage_backend=stored.storage_backend,
            bucket=stored.bucket,
            storage_key=stored.storage_key,
            storage_ref=stored.storage_ref,
            checksum=stored.checksum,
            content_type=stored.content_type,
        )


def safe_file_name(value: str) -> str:
    normalized = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", normalized).strip(".-")
    return normalized or "file"


def slugify(value: str) -> str:
    normalized = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "item"
