from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.storage.models import StorageObject
from app.platform.storage.service import StoredObject


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

    async def upsert(
        self,
        stored: StoredObject,
        *,
        owner_entity_type: str,
        owner_entity_id: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        statement = postgresql_insert(StorageObject).values(
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
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[StorageObject.storage_key],
                set_={
                    "owner_entity_type": owner_entity_type,
                    "owner_entity_id": owner_entity_id,
                    "storage_backend": stored.storage_backend,
                    "bucket": stored.bucket,
                    "storage_ref": stored.storage_ref,
                    "content_type": stored.content_type,
                    "size_bytes": stored.size_bytes,
                    "checksum": stored.checksum,
                    "metadata": metadata or {},
                },
            )
        )
