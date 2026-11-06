"""Periodic content housekeeping (run by the `maintenance` worker module)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.logging import get_logger
from app.modules.content.deletion import hard_delete_objects
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.content.models import ContentFileUpload, ContentObject
from app.modules.content.sync import prune_tombstones
from app.platform.storage.keys import (
    OBJECTS_PREFIX,
    UPLOADS_PREFIX,
    object_prefix,
    upload_owner_prefix,
    upload_prefix,
)
from app.worker.context import WorkerContext

logger = get_logger(__name__)

PURGE_BATCH = 100
UPLOAD_BATCH = 200
# Storage prefixes without a DB row are deleted only when untouched for this long, so files
# written by an in-flight request (before its commit) are never swept.
ORPHAN_GRACE = timedelta(hours=24)
ORPHAN_CHECK_BATCH = 500
ORPHAN_MAX_DELETES_PER_RUN = 200


async def run_content_maintenance(ctx: WorkerContext) -> None:
    purged = await _purge_expired_trash(ctx)
    expired = await _expire_pending_uploads(ctx)
    async with ctx.session_factory() as session:
        tombstones = await prune_tombstones(session)
        await session.commit()
    orphans = await _sweep_orphans(ctx)
    logger.info(
        "content.maintenance.done",
        purged_notes=purged,
        expired_uploads=expired,
        pruned_tombstones=tombstones,
        orphan_prefixes=orphans,
    )


async def _purge_expired_trash(ctx: WorkerContext) -> int:
    """Hard-delete notes whose trash retention ended (`delete_after`, set from the user's
    retention setting, defaulting to `trash_retention_days`)."""
    total = 0
    fallback_cutoff = datetime.now(UTC) - timedelta(days=ctx.settings.trash_retention_days)
    while True:
        async with ctx.session_factory() as session:
            now = datetime.now(UTC)
            rows = (
                await session.execute(
                    select(ContentObject.id, ContentObject.owner_user_id)
                    .where(
                        ContentObject.deleted_at.is_not(None),
                        (ContentObject.delete_after <= now)
                        | (
                            ContentObject.delete_after.is_(None)
                            & (ContentObject.deleted_at <= fallback_cutoff)
                        ),
                    )
                    .order_by(ContentObject.delete_after.asc().nulls_first())
                    .limit(PURGE_BATCH)
                )
            ).all()
            if not rows:
                return total
            by_owner: dict[str, list[str]] = defaultdict(list)
            for object_id, owner_user_id in rows:
                by_owner[owner_user_id].append(object_id)
            repository = ContentRepository(session)
            for owner_user_id, ids in by_owner.items():
                tree = await repository.descendant_ids(ids)
                total += await hard_delete_objects(
                    session, ctx.storage, owner_user_id=owner_user_id, ids=tree
                )
            if len(rows) < PURGE_BATCH:
                return total


async def _expire_pending_uploads(ctx: WorkerContext) -> int:
    total = 0
    while True:
        async with ctx.session_factory() as session:
            rows = (
                await session.execute(
                    delete(ContentFileUpload)
                    .where(
                        ContentFileUpload.id.in_(
                            select(ContentFileUpload.id)
                            .where(ContentFileUpload.expires_at <= datetime.now(UTC))
                            .limit(UPLOAD_BATCH)
                        )
                    )
                    .returning(ContentFileUpload.id, ContentFileUpload.owner_user_id)
                )
            ).all()
            await session.commit()
        for upload_id, owner_user_id in rows:
            try:
                await ctx.storage.delete_prefix(upload_prefix(owner_user_id, upload_id))
            except Exception:  # noqa: BLE001 - orphan sweep retries
                logger.warning("content.maintenance.upload_delete_failed", exc_info=True)
        total += len(rows)
        if len(rows) < UPLOAD_BATCH:
            return total


async def _sweep_orphans(ctx: WorkerContext) -> int:
    """Delete storage prefixes that no DB row references (crashed requests, failed purges)."""
    deleted = 0
    candidates = await ctx.storage.list_prefixes(OBJECTS_PREFIX)
    for start in range(0, len(candidates), ORPHAN_CHECK_BATCH):
        if deleted >= ORPHAN_MAX_DELETES_PER_RUN:
            break
        batch = candidates[start : start + ORPHAN_CHECK_BATCH]
        async with ctx.session_factory() as session:
            live_objects = set(
                await session.scalars(select(ContentObject.id).where(ContentObject.id.in_(batch)))
            )
            unknown = [object_id for object_id in batch if object_id not in live_objects]
            busy = await ContentRepository(session).live_prefixes(
                [object_prefix(object_id) for object_id in unknown]
            )
        for object_id in unknown:
            prefix = object_prefix(object_id)
            if prefix in busy or deleted >= ORPHAN_MAX_DELETES_PER_RUN:
                continue
            deleted += await _delete_if_stale(ctx, prefix)

    for owner in await ctx.storage.list_prefixes(UPLOADS_PREFIX):
        if deleted >= ORPHAN_MAX_DELETES_PER_RUN:
            break
        upload_ids = await ctx.storage.list_prefixes(upload_owner_prefix(owner))
        if not upload_ids:
            continue
        async with ctx.session_factory() as session:
            known = set(
                await session.scalars(
                    select(ContentFileUpload.id).where(ContentFileUpload.id.in_(upload_ids))
                )
            )
        for upload_id in upload_ids:
            if upload_id not in known and deleted < ORPHAN_MAX_DELETES_PER_RUN:
                deleted += await _delete_if_stale(ctx, upload_prefix(owner, upload_id))
    return deleted


async def _delete_if_stale(ctx: WorkerContext, prefix: str) -> int:
    try:
        modified = await ctx.storage.prefix_modified_at(prefix)
        if modified is not None and modified > datetime.now(UTC) - ORPHAN_GRACE:
            return 0
        await ctx.storage.delete_prefix(prefix)
    except Exception:  # noqa: BLE001 - retried next run
        logger.warning("content.maintenance.orphan_delete_failed", prefix=prefix, exc_info=True)
        return 0
    logger.info("content.maintenance.orphan_deleted", prefix=prefix)
    return 1
