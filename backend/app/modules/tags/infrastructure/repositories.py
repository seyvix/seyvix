from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any
from typing import cast as type_cast
from uuid import uuid4

from sqlalchemy import ColumnElement, Text, case, cast, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.tags.models import (
    ACTIVE_ASSIGNMENT_STATUSES,
    ContentTagAssignment,
    Tag,
    TaggingJob,
)
from app.platform.jobs import JOB_PENDING, JOB_PROCESSING, utcnow

_SIMPLE: ColumnElement[Any] = literal_column("'simple'::regconfig")


class TagsRepository:
    """Queries only; the caller owns the transaction (no commits here)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- tags ------------------------------------------------------------------------------
    async def get_tag(self, *, owner_user_id: str, tag_id: str) -> Tag | None:
        query = select(Tag).where(Tag.owner_user_id == owner_user_id, Tag.id == tag_id)
        return type_cast(Tag | None, await self.session.scalar(query))

    async def list_tags(self, *, owner_user_id: str, include_archived: bool) -> list[Tag]:
        query = select(Tag).where(Tag.owner_user_id == owner_user_id)
        if not include_archived:
            query = query.where(Tag.is_archived.is_(False))
        return list(await self.session.scalars(query.order_by(Tag.name.asc())))

    async def find_tags_by_slugs(
        self,
        *,
        owner_user_id: str,
        slugs: Collection[str],
        except_tag_id: str | None = None,
    ) -> list[Tag]:
        """Tags (archived included) whose slug or one of whose aliases is in `slugs`."""
        if not slugs:
            return []
        values = list(slugs)
        query = select(Tag).where(
            Tag.owner_user_id == owner_user_id,
            or_(Tag.slug.in_(values), Tag.aliases.has_any(array(values, type_=Text()))),
        )
        if except_tag_id is not None:
            query = query.where(Tag.id != except_tag_id)
        return list(await self.session.scalars(query))

    async def insert_missing_tags(self, rows: Sequence[dict[str, Any]]) -> None:
        """Insert tags, silently skipping slugs that already exist (concurrent creation)."""
        if not rows:
            return
        statement = pg_insert(Tag).values(list(rows))
        await self.session.execute(
            statement.on_conflict_do_nothing(index_elements=[Tag.owner_user_id, Tag.slug])
        )

    async def candidate_tags(
        self,
        *,
        owner_user_id: str,
        tokens: Sequence[str],
        limit: int,
    ) -> list[Tag]:
        """Best full-text matches of the user's active tags against content tokens."""
        if not tokens:
            return []
        document = func.to_tsvector(
            _SIMPLE,
            func.concat_ws(
                " ",
                Tag.name,
                func.replace(Tag.slug, "-", " "),
                cast(Tag.aliases, Text()),
                Tag.description,
                Tag.tag_kind,
            ),
        )
        ts_query = func.to_tsquery(_SIMPLE, " | ".join(tokens))
        rank = func.ts_rank(document, ts_query)
        query = (
            select(Tag)
            .where(
                Tag.owner_user_id == owner_user_id,
                Tag.is_archived.is_(False),
                document.op("@@")(ts_query),
            )
            .order_by(rank.desc(), Tag.name.asc())
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    # --- assignments -----------------------------------------------------------------------
    async def list_assignments_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        statuses: Collection[str] = ACTIVE_ASSIGNMENT_STATUSES,
    ) -> list[ContentTagAssignment]:
        query = (
            select(ContentTagAssignment)
            .join(Tag, ContentTagAssignment.tag_id == Tag.id)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.content_object_id == content_object_id,
                ContentTagAssignment.status.in_(list(statuses)),
            )
            .order_by(Tag.name.asc())
        )
        return list(await self.session.scalars(query))

    async def list_assignments_for_contents(
        self,
        *,
        owner_user_id: str,
        content_object_ids: Collection[str],
        statuses: Collection[str],
    ) -> list[ContentTagAssignment]:
        if not content_object_ids:
            return []
        query = (
            select(ContentTagAssignment)
            .join(Tag, ContentTagAssignment.tag_id == Tag.id)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.content_object_id.in_(list(content_object_ids)),
                ContentTagAssignment.status.in_(list(statuses)),
            )
            .order_by(Tag.name.asc())
        )
        return list(await self.session.scalars(query))

    async def list_review_suggestions(
        self, *, owner_user_id: str, limit: int, offset: int
    ) -> list[ContentTagAssignment]:
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.status == "suggested",
            )
            .order_by(ContentTagAssignment.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def get_assignment(
        self, *, owner_user_id: str, assignment_id: str
    ) -> ContentTagAssignment | None:
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.id == assignment_id,
            )
        )
        return type_cast(ContentTagAssignment | None, await self.session.scalar(query))

    async def get_active_assignment(
        self, *, owner_user_id: str, content_object_id: str, tag_id: str
    ) -> ContentTagAssignment | None:
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.content_object_id == content_object_id,
                ContentTagAssignment.tag_id == tag_id,
                ContentTagAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
            )
        )
        return type_cast(ContentTagAssignment | None, await self.session.scalar(query))

    async def count_suggestions(self, *, owner_user_id: str) -> int:
        count = await self.session.scalar(
            select(func.count(ContentTagAssignment.id)).where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.status == "suggested",
            )
        )
        return int(count or 0)

    # --- jobs ------------------------------------------------------------------------------
    async def enqueue_job(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        job_type: str,
        priority: int,
        max_attempts: int,
        source_event_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        return await upsert_content_job(
            self.session,
            TaggingJob,
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type=job_type,
            priority=priority,
            max_attempts=max_attempts,
            source_event_id=source_event_id,
            correlation_id=correlation_id,
        )

    async def get_job(self, job_id: str, *, for_update: bool = False) -> TaggingJob | None:
        query = select(TaggingJob).where(TaggingJob.id == job_id)
        if for_update:
            query = query.with_for_update()
        return type_cast(TaggingJob | None, await self.session.scalar(query))

    async def list_jobs_for_content(
        self, *, owner_user_id: str, content_object_id: str
    ) -> list[TaggingJob]:
        query = (
            select(TaggingJob)
            .where(
                TaggingJob.owner_user_id == owner_user_id,
                TaggingJob.content_object_id == content_object_id,
            )
            .order_by(TaggingJob.created_at.desc())
        )
        return list(await self.session.scalars(query))

    async def count_jobs_by_status(self, *, owner_user_id: str) -> list[tuple[str, int]]:
        rows = await self.session.execute(
            select(TaggingJob.status, func.count(TaggingJob.id))
            .where(TaggingJob.owner_user_id == owner_user_id)
            .group_by(TaggingJob.status)
        )
        return [(str(status), int(count)) for status, count in rows.all()]


def index_tags_by_slug(tags: Sequence[Tag]) -> dict[str, Tag]:
    """Map slugs and alias slugs to tags.

    Precedence (highest last): archived alias, archived slug, active alias, active slug —
    so a merged (archived) tag's slug resolves to the tag it was merged into.
    """
    indexed: dict[str, Tag] = {}
    for archived in (True, False):
        group = [tag for tag in tags if tag.is_archived is archived]
        for tag in group:
            for alias in tag.aliases or []:
                indexed[alias] = tag
        for tag in group:
            indexed[tag.slug] = tag
    return indexed


async def upsert_content_job(
    session: AsyncSession,
    model: type[Any],
    *,
    owner_user_id: str,
    content_object_id: str,
    job_type: str,
    priority: int,
    max_attempts: int,
    source_event_id: str | None,
    correlation_id: str | None,
) -> str:
    [job_id] = await upsert_content_jobs(
        session,
        model,
        owner_user_id=owner_user_id,
        content_object_ids=[content_object_id],
        job_type=job_type,
        priority=priority,
        max_attempts=max_attempts,
        source_event_id=source_event_id,
        correlation_id=correlation_id,
    )
    return job_id


async def upsert_content_jobs(
    session: AsyncSession,
    model: type[Any],
    *,
    owner_user_id: str,
    content_object_ids: Sequence[str],
    job_type: str,
    priority: int,
    max_attempts: int,
    source_event_id: str | None,
    correlation_id: str | None,
) -> list[str]:
    """Duplicate-safe enqueue (one statement) for job tables keyed by
    (content_object_id, job_type) — the tags and taxonomy tables.

    A finished row is reset to pending; a pending row becomes due now and may gain
    priority; a processing row is flagged `rerun_requested` so it runs once more after
    the current attempt, which may have read input that is now outdated.
    """
    if not content_object_ids:
        return []
    now = utcnow()
    processing = model.status == JOB_PROCESSING
    insert = pg_insert(model).values(
        [
            {
                "id": str(uuid4()),
                "owner_user_id": owner_user_id,
                "content_object_id": content_object_id,
                "job_type": job_type,
                "status": JOB_PENDING,
                "priority": priority,
                "attempts": 0,
                "max_attempts": max_attempts,
                "run_after": now,
                "rerun_requested": False,
                "source_event_id": source_event_id,
                "correlation_id": correlation_id,
                "created_at": now,
                "updated_at": now,
            }
            for content_object_id in dict.fromkeys(content_object_ids)
        ]
    )
    excluded = insert.excluded
    statement = insert.on_conflict_do_update(
        index_elements=[model.content_object_id, model.job_type],
        set_={
            "rerun_requested": processing,
            "status": case((processing, model.status), else_=JOB_PENDING),
            "attempts": case((processing, model.attempts), else_=0),
            "max_attempts": excluded.max_attempts,
            "run_after": case(
                (processing, model.run_after),
                else_=func.least(model.run_after, excluded.run_after),
            ),
            "priority": func.greatest(model.priority, excluded.priority),
            "last_error": case((processing, model.last_error), else_=None),
            "source_event_id": func.coalesce(excluded.source_event_id, model.source_event_id),
            "correlation_id": func.coalesce(excluded.correlation_id, model.correlation_id),
            "updated_at": now,
        },
    ).returning(model.id)
    return [str(job_id) for job_id in (await session.scalars(statement))]
