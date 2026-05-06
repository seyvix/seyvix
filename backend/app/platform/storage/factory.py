from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.platform.storage.service import LocalVolumeStorage, S3CompatibleStorage, StorageBackend


def build_storage_backend(settings: Settings, *, local_root: Path | None = None) -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3CompatibleStorage(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    return LocalVolumeStorage(
        root=local_root or Path(settings.content_storage_root),
        bucket=settings.s3_bucket,
    )
