from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from unicodedata import normalize

from app.modules.content.models import ContentObject


@dataclass(slots=True)
class StoredFile:
    filename: str
    relative_path: str
    size_bytes: int


class ContentStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

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
        directory: Path,
        title: str,
        text: str,
    ) -> StoredFile:
        directory.mkdir(parents=True, exist_ok=True)
        filename = "content.md"
        content = f"# {title}\n\n{text}\n"
        path = directory / filename
        path.write_text(content, encoding="utf-8")
        return StoredFile(
            filename=filename,
            relative_path=self._relative(path),
            size_bytes=path.stat().st_size,
        )

    def write_binary_object(
        self,
        *,
        directory: Path,
        filename: str,
        data: bytes,
    ) -> StoredFile:
        original_dir = directory / "original"
        original_dir.mkdir(parents=True, exist_ok=True)
        safe_filename = safe_file_name(filename)
        path = original_dir / safe_filename
        path.write_bytes(data)
        return StoredFile(
            filename=safe_filename,
            relative_path=self._relative(path),
            size_bytes=path.stat().st_size,
        )

    def write_temp_file(
        self,
        *,
        owner_user_id: str,
        upload_id: str,
        filename: str,
        data: bytes,
    ) -> StoredFile:
        upload_dir = self.root / owner_user_id / ".uploads" / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_filename = safe_file_name(filename)
        path = upload_dir / safe_filename
        path.write_bytes(data)
        return StoredFile(
            filename=safe_filename,
            relative_path=self._relative(path),
            size_bytes=path.stat().st_size,
        )

    def read_relative_file(self, relative_path: str) -> bytes:
        return (self.root / relative_path).read_bytes()

    def write_manifest(self, *, directory: Path, manifest: dict[str, object]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "manifest.json"
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def build_archive(self, content_object: ContentObject) -> Path:
        source_dir = self.root / content_object.storage_path
        temp_file = NamedTemporaryFile(
            prefix=f"{content_object.slug}-",
            suffix=".zip",
            delete=False,
        )
        temp_file.close()
        archive_path = Path(temp_file.name)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if source_dir.exists():
                for path in source_dir.rglob("*"):
                    if path.is_file():
                        archive.write(path, arcname=path.relative_to(source_dir))
            else:
                archive.writestr("manifest.json", "{}")
        return archive_path

    def remove_directory(self, content_object: ContentObject) -> None:
        path = self.root / content_object.storage_path
        if path.exists():
            shutil.rmtree(path)

    def remove_relative_file_parent(self, relative_path: str) -> None:
        path = self.root / relative_path
        if path.exists():
            path.unlink()
        parent = path.parent
        if parent.exists() and parent != self.root:
            shutil.rmtree(parent)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def safe_file_name(value: str) -> str:
    normalized = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", normalized).strip(".-")
    return normalized or "file"


def slugify(value: str) -> str:
    normalized = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "item"
