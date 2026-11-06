"""Change feed for note cards (`GET /notes/changes`).

`content_objects.changed_at` is bumped whenever anything that affects how a note renders
changes. Other modules call `touch_content_objects` in the same transaction as their result
write. Hard deletes leave a short-lived tombstone so clients learn about removals.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import ContentCollectionItem, ContentObject, ContentTombstone

# Cursors older than this (and tombstones) are discarded; clients then refetch their lists.
CHANGE_FEED_RETENTION = timedelta(days=7)
CHANGE_FEED_PAGE_SIZE = 200
COMMIT_SKEW = timedelta(seconds=5)


async def touch_content_objects(session: AsyncSession, ids: Iterable[str]) -> None:
    """Mark notes (and the collections containing them) as changed. Does not load rows and
    does not modify `updated_at` (which tracks content edits)."""
    unique_ids = list(dict.fromkeys(item for item in ids if item))
    if not unique_ids:
        return
    parent_ids = select(ContentCollectionItem.collection_id).where(
        ContentCollectionItem.content_object_id.in_(unique_ids)
    )
    await session.execute(
        update(ContentObject)
        .where(or_(ContentObject.id.in_(unique_ids), ContentObject.id.in_(parent_ids)))
        .values(changed_at=func.clock_timestamp(), updated_at=ContentObject.updated_at)
        .execution_options(synchronize_session=False)
    )


async def record_tombstones(session: AsyncSession, owner_user_id: str, ids: Iterable[str]) -> None:
    rows = [{"content_object_id": item, "owner_user_id": owner_user_id} for item in ids]
    if not rows:
        return
    statement = postgresql_insert(ContentTombstone).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[ContentTombstone.content_object_id],
            set_={"deleted_at": func.clock_timestamp()},
        )
    )


async def prune_tombstones(session: AsyncSession) -> int:
    result = await session.execute(
        delete(ContentTombstone).where(
            ContentTombstone.deleted_at < datetime.now(UTC) - CHANGE_FEED_RETENTION
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(frozen=True, slots=True)
class ChangeSet:
    cursor: str
    # Live, top-level notes changed since the cursor (oldest change first).
    changed_ids: list[str]
    removed_ids: list[str]
    reset: bool
    has_more: bool


def _parse_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    if parsed < datetime.now(UTC) - CHANGE_FEED_RETENTION:
        return None
    return parsed


def _format_cursor(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


async def _current_cursor(session: AsyncSession, owner_user_id: str) -> str:
    latest = await session.scalar(
        select(func.max(ContentObject.changed_at)).where(
            ContentObject.owner_user_id == owner_user_id
        )
    )
    tomb = await session.scalar(
        select(func.max(ContentTombstone.deleted_at)).where(
            ContentTombstone.owner_user_id == owner_user_id
        )
    )
    candidates = [value for value in (latest, tomb) if value is not None]
    return _format_cursor(max(candidates) if candidates else datetime.now(UTC))


async def load_changes(
    session: AsyncSession,
    *,
    owner_user_id: str,
    since: str | None,
    limit: int = CHANGE_FEED_PAGE_SIZE,
) -> ChangeSet:
    since_at = _parse_cursor(since)
    if since_at is None:
        return ChangeSet(
            cursor=await _current_cursor(session, owner_user_id),
            changed_ids=[],
            removed_ids=[],
            reset=True,
            has_more=False,
        )

    is_child = (
        select(ContentCollectionItem.id)
        .where(ContentCollectionItem.content_object_id == ContentObject.id)
        .exists()
    )
    rows = (
        await session.execute(
            select(
                ContentObject.id,
                ContentObject.changed_at,
                ContentObject.deleted_at.is_not(None).label("is_deleted"),
                (is_child & (ContentObject.kind != "collection")).label("is_child"),
            )
            .where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.changed_at > since_at,
            )
            .order_by(ContentObject.changed_at.asc(), ContentObject.id.asc())
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    changed_ids: list[str] = []
    removed_ids: list[str] = []
    for row in rows:
        if row.is_deleted or row.is_child:
            removed_ids.append(row.id)
        else:
            changed_ids.append(row.id)
    max_seen: datetime = rows[-1].changed_at if rows else since_at

    if not has_more:
        tombstones = (
            await session.execute(
                select(ContentTombstone.content_object_id, ContentTombstone.deleted_at).where(
                    ContentTombstone.owner_user_id == owner_user_id,
                    ContentTombstone.deleted_at > since_at,
                )
            )
        ).all()
        for tombstone in tombstones:
            removed_ids.append(tombstone.content_object_id)
            max_seen = max(max_seen, tombstone.deleted_at)

    # Transactions commit out of `changed_at` order; keep the cursor slightly behind "now" so
    # late commits are picked up by the next poll (re-sent cards are harmless upserts).
    horizon = datetime.now(UTC) - COMMIT_SKEW
    cursor_at = max_seen if has_more or max_seen <= horizon else max(horizon, since_at)
    return ChangeSet(
        cursor=_format_cursor(cursor_at),
        changed_ids=changed_ids,
        removed_ids=list(dict.fromkeys(removed_ids)),
        reset=False,
        has_more=has_more,
    )
