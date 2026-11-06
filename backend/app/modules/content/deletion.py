"""Trash, restore and permanent deletion (DB first, then storage, best effort)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import ContentObjectChangedPayload, EventEnvelope
from app.core.logging import get_logger
from app.modules.content.errors import NoteNotFoundError
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.content.sync import record_tombstones
from app.modules.taxonomy.service import TaxonomyService
from app.platform.events import EventPublisher
from app.platform.storage.keys import asset_dir, object_id_from_key, object_prefix
from app.platform.storage.service import StorageBackend

logger = get_logger(__name__)


def _publish(session: AsyncSession, owner_user_id: str, ids: Sequence[str], name: str) -> None:
    publisher = EventPublisher(session)
    for object_id in ids:
        publisher.publish(
            EventEnvelope.new(
                event_name=name,  # type: ignore[arg-type]
                entity_id=object_id,
                correlation_id=str(uuid4()),
                user_id=owner_user_id,
                payload=ContentObjectChangedPayload(content_object_id=object_id),
            )
        )


async def hard_delete_objects(
    session: AsyncSession, storage: StorageBackend, *, owner_user_id: str, ids: Sequence[str]
) -> int:
    """Permanently delete notes (callers pass the full tree, see `descendant_ids`).

    Rows are deleted and committed first; files are removed afterwards. A storage failure
    only leaves orphans, which the maintenance sweep removes later.
    """
    if not ids:
        return 0
    asset_keys = list(
        await session.scalars(
            select(ContentAsset.storage_key).where(ContentAsset.content_object_id.in_(ids))
        )
    )
    _publish(session, owner_user_id, ids, "content.object.deleted")
    await record_tombstones(session, owner_user_id, ids)
    result = await session.execute(
        delete(ContentObject).where(
            ContentObject.owner_user_id == owner_user_id, ContentObject.id.in_(ids)
        )
    )
    await session.commit()
    await purge_storage(session, storage, object_ids=ids, asset_keys=asset_keys)
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_storage(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    object_ids: Sequence[str],
    asset_keys: Sequence[str],
) -> None:
    """Remove files of deleted notes. Whole `objects/{id}/` prefixes go when no live object
    or asset still uses them (assets keep their key when moved between notes); otherwise only
    the deleted assets' own directories are removed."""
    repository = ContentRepository(session)
    prefixes = {object_prefix(object_id) for object_id in object_ids}
    for key in asset_keys:
        owner_id = object_id_from_key(key)
        if owner_id is not None:
            prefixes.add(object_prefix(owner_id))
    try:
        busy = await repository.live_prefixes(sorted(prefixes))
        prefix_ids = {prefix.split("/")[1]: prefix for prefix in prefixes}
        existing = set(
            await session.scalars(
                select(ContentObject.id).where(ContentObject.id.in_(list(prefix_ids)))
            )
        )
        busy |= {prefix_ids[object_id] for object_id in existing}
        await session.commit()
    except Exception:
        logger.exception("content.storage.purge_check_failed", objects=len(object_ids))
        return
    removed = 0
    for prefix in sorted(prefixes - busy):
        try:
            removed += await storage.delete_prefix(prefix)
        except Exception:  # noqa: BLE001 - orphan sweep retries later
            logger.warning("content.storage.delete_prefix_failed", prefix=prefix, exc_info=True)
    for key in asset_keys:
        directory = asset_dir(key)
        if any(directory.startswith(prefix) for prefix in busy):
            try:
                removed += await storage.delete_prefix(directory)
            except Exception:  # noqa: BLE001 - orphan sweep retries later
                logger.warning(
                    "content.storage.delete_prefix_failed", prefix=directory, exc_info=True
                )
    logger.info("content.storage.purged", objects=len(object_ids), files=removed)


class NoteDeleter:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        *,
        repository: ContentRepository,
        taxonomy: TaxonomyService,
    ) -> None:
        self.session = session
        self.storage = storage
        self.repository = repository
        self.taxonomy = taxonomy

    async def delete_notes(self, *, owner_user_id: str, slugs: Sequence[str]) -> None:
        objects = await self.repository.list_by_slugs(owner_user_id=owner_user_id, slugs=slugs)
        ids = await self.repository.descendant_ids([obj.id for obj in objects])
        if not ids:
            return
        settings = await self.taxonomy.get_user_settings(owner_user_id=owner_user_id)
        if not settings.trash_enabled:
            await hard_delete_objects(
                self.session, self.storage, owner_user_id=owner_user_id, ids=ids
            )
            return
        now = datetime.now(UTC)
        await self.session.execute(
            update(ContentObject)
            .where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.id.in_(ids),
                ContentObject.deleted_at.is_(None),
            )
            .values(
                deleted_at=now,
                delete_after=now + timedelta(days=settings.trash_retention_days),
                changed_at=func.clock_timestamp(),
            )
            .execution_options(synchronize_session=False)
        )
        _publish(self.session, owner_user_id, ids, "content.object.deleted")
        await self.session.commit()

    async def restore(self, *, owner_user_id: str, slug: str) -> str:
        content_object = await self.repository.get_by_slug(
            owner_user_id=owner_user_id, slug=slug, include_deleted=True
        )
        if content_object is None or content_object.deleted_at is None:
            raise NoteNotFoundError
        ids = await self.repository.descendant_ids([content_object.id])
        await self.session.execute(
            update(ContentObject)
            .where(ContentObject.owner_user_id == owner_user_id, ContentObject.id.in_(ids))
            .values(deleted_at=None, delete_after=None, changed_at=func.clock_timestamp())
            .execution_options(synchronize_session=False)
        )
        _publish(self.session, owner_user_id, ids, "content.object.updated")
        await self.session.commit()
        return content_object.id

    async def cleanup_expired_trash(self, *, owner_user_id: str) -> int:
        expired = list(
            await self.session.scalars(
                select(ContentObject.id).where(
                    ContentObject.owner_user_id == owner_user_id,
                    ContentObject.deleted_at.is_not(None),
                    ContentObject.delete_after <= datetime.now(UTC),
                )
            )
        )
        ids = await self.repository.descendant_ids(expired)
        return await hard_delete_objects(
            self.session, self.storage, owner_user_id=owner_user_id, ids=ids
        )
