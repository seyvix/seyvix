from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.platform.storage.local import LocalVolumeStorage
from app.platform.storage.s3 import S3Storage
from app.platform.storage.service import StorageBackend


def build_storage_backend(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    return LocalVolumeStorage(Path(settings.content_storage_root))
