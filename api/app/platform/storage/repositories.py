from __future__ import annotations

from app.platform.storage.models import StorageObject
from app.platform.storage.service import StoredObject
from sqlalchemy.ext.asyncio import AsyncSession


class StorageObjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(
        self,
        stored: StoredObject,
        *,
        owner_entity_type: str,
        owner_entity_id: str,
        metadata: dict[str, object] | None = None,
    ) -> StorageObject:
        row = StorageObject(
            owner_entity_type=owner_entity_type,
            owner_entity_id=owner_entity_id,
            storage_backend=stored.storage_backend,
            bucket=stored.bucket,
            storage_key=stored.storage_key,
            storage_ref=stored.storage_ref,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            checksum=stored.checksum,
            metadata_=metadata or {},
        )
        self.session.add(row)
        return row
