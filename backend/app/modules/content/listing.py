"""Note listing, trash and folders with filtering, ordering and pagination done in SQL."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import ColumnElement, Select, String, and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.content.models import ContentCollectionItem, ContentObject, ContentSource
from app.modules.content.text import slugify
from app.modules.tags.models import ContentTagAssignment, Tag
from app.modules.taxonomy.models import TaxonomyCategory, TaxonomyContentAssignment

# Upper bound for unpaginated requests (keeps memory bounded on huge libraries).
MAX_PAGE_SIZE = 500
ACCEPTED_TAG_STATUS = "accepted"


@dataclass(frozen=True, slots=True)
class NoteFilters:
    tag_slugs: Sequence[str] = ()
    folder_path: str | None = None
    content_types: Sequence[str] = ()
    source_providers: Sequence[str] = ()
    is_favorite: bool | None = None
    created_at_from: datetime | None = None
    created_at_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class NotePage:
    ids: list[str]
    next_offset: int | None


@dataclass(slots=True)
class FolderStats:
    direct: dict[str, int] = field(default_factory=dict)
    total: dict[str, int] = field(default_factory=dict)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_top_level() -> ColumnElement[bool]:
    is_member = (
        select(ContentCollectionItem.id)
        .where(ContentCollectionItem.content_object_id == ContentObject.id)
        .exists()
    )
    return or_(ContentObject.kind == "collection", ~is_member)


def _path_condition(
    column: ColumnElement[str] | InstrumentedAttribute[str], folder_path: str
) -> ColumnElement[bool]:
    return or_(column == folder_path, column.like(f"{_escape_like(folder_path)}/%", escape="\\"))


def _current_path() -> ColumnElement[str]:
    return (
        select(TaxonomyContentAssignment.category_path_snapshot)
        .where(
            TaxonomyContentAssignment.content_object_id == ContentObject.id,
            TaxonomyContentAssignment.is_current.is_(True),
        )
        .limit(1)
        .scalar_subquery()
    )


def _content_type_condition(values: Sequence[str]) -> ColumnElement[bool] | None:
    conditions: list[ColumnElement[bool]] = []
    for raw in values:
        value = raw.strip().casefold()
        if not value:
            continue
        if value in {"note", "notes", "text"}:
            conditions.append(
                or_(ContentObject.media_type.is_(None), ContentObject.media_type == "text")
            )
        elif value == "collection":
            conditions.append(ContentObject.kind == "collection")
        elif value == "pdf":
            conditions.append(
                and_(
                    ContentObject.media_type == "document",
                    or_(
                        ContentObject.mime_type == "application/pdf",
                        func.lower(ContentObject.source_filename).like("%.pdf"),
                    ),
                )
            )
        else:
            conditions.append(ContentObject.media_type == value)
    return or_(*conditions) if conditions else None


def apply_filters(
    query: Select[tuple[str]], owner_user_id: str, filters: NoteFilters
) -> Select[tuple[str]]:
    query = query.where(
        ContentObject.owner_user_id == owner_user_id, ContentObject.deleted_at.is_(None)
    )
    if filters.folder_path:
        query = query.where(
            select(TaxonomyContentAssignment.id)
            .where(
                TaxonomyContentAssignment.content_object_id == ContentObject.id,
                TaxonomyContentAssignment.is_current.is_(True),
                _path_condition(
                    TaxonomyContentAssignment.category_path_snapshot, filters.folder_path
                ),
            )
            .exists()
        )
    for slug in dict.fromkeys(slugify(tag) for tag in filters.tag_slugs if tag.strip()):
        query = query.where(
            select(ContentTagAssignment.id)
            .join(Tag, Tag.id == ContentTagAssignment.tag_id)
            .where(
                ContentTagAssignment.content_object_id == ContentObject.id,
                ContentTagAssignment.status == ACCEPTED_TAG_STATUS,
                Tag.slug == slug,
            )
            .exists()
        )
    type_condition = _content_type_condition(filters.content_types)
    if type_condition is not None:
        query = query.where(type_condition)
    providers = sorted({p.strip().casefold() for p in filters.source_providers if p.strip()})
    if providers:
        query = query.where(
            select(ContentSource.id)
            .where(
                ContentSource.content_object_id == ContentObject.id,
                func.lower(ContentSource.provider).in_(providers),
            )
            .exists()
        )
    if filters.is_favorite is not None:
        query = query.where(ContentObject.is_favorite.is_(filters.is_favorite))
    if filters.created_at_from is not None:
        query = query.where(ContentObject.created_at >= filters.created_at_from)
    if filters.created_at_to is not None:
        query = query.where(ContentObject.created_at <= filters.created_at_to)
    return query


class NoteLister:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_ids(
        self,
        *,
        owner_user_id: str,
        filters: NoteFilters,
        sort: str,
        limit: int | None,
        offset: int,
        search_ids: Sequence[str] | None = None,
    ) -> NotePage:
        """Ids of one page of notes. Without search only top-level notes are listed; with
        search the ranked candidates (children included) are filtered and kept in rank order."""
        query = apply_filters(select(ContentObject.id), owner_user_id, filters)
        if search_ids is not None:
            if not search_ids:
                return NotePage(ids=[], next_offset=None)
            ranked = list(search_ids)
            query = query.where(ContentObject.id.in_(ranked)).order_by(
                func.array_position(literal(ranked, type_=ARRAY(String)), ContentObject.id)
            )
        else:
            query = query.where(_is_top_level())
            if sort == "custom":
                query = query.order_by(
                    ContentObject.sort_order.asc(),
                    ContentObject.created_at.asc(),
                    ContentObject.id.asc(),
                )
            elif filters.folder_path:
                query = query.order_by(
                    (func.coalesce(_current_path(), "") != filters.folder_path).asc(),
                    ContentObject.created_at.desc(),
                    ContentObject.id.desc(),
                )
            else:
                query = query.order_by(ContentObject.created_at.desc(), ContentObject.id.desc())
        page_size = min(limit or MAX_PAGE_SIZE, MAX_PAGE_SIZE)
        start = max(offset, 0)
        rows = list(await self.session.scalars(query.offset(start).limit(page_size + 1)))
        next_offset = start + page_size if len(rows) > page_size else None
        return NotePage(ids=rows[:page_size], next_offset=next_offset)

    async def trash_ids(self, *, owner_user_id: str) -> list[str]:
        query = (
            select(ContentObject.id)
            .where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.deleted_at.is_not(None),
                _is_top_level(),
            )
            .order_by(ContentObject.deleted_at.desc(), ContentObject.id.asc())
            .limit(MAX_PAGE_SIZE)
        )
        return list(await self.session.scalars(query))

    async def categories(self, *, owner_user_id: str) -> list[TaxonomyCategory]:
        return list(
            await self.session.scalars(
                select(TaxonomyCategory)
                .where(
                    TaxonomyCategory.owner_user_id == owner_user_id,
                    TaxonomyCategory.is_archived.is_(False),
                )
                .order_by(
                    TaxonomyCategory.depth.asc(),
                    TaxonomyCategory.sort_order.asc(),
                    TaxonomyCategory.name.asc(),
                )
            )
        )

    async def folder_stats(self, *, owner_user_id: str, paths: Sequence[str]) -> FolderStats:
        """Direct and recursive counts of visible notes per folder path (one GROUP BY)."""
        rows = (
            await self.session.execute(
                select(TaxonomyContentAssignment.category_path_snapshot, func.count())
                .join(
                    ContentObject,
                    ContentObject.id == TaxonomyContentAssignment.content_object_id,
                )
                .where(
                    TaxonomyContentAssignment.owner_user_id == owner_user_id,
                    TaxonomyContentAssignment.is_current.is_(True),
                    ContentObject.deleted_at.is_(None),
                    _is_top_level(),
                )
                .group_by(TaxonomyContentAssignment.category_path_snapshot)
            )
        ).all()
        by_path = {path: int(count) for path, count in rows}
        stats = FolderStats()
        for path in paths:
            stats.direct[path] = by_path.get(path, 0)
            prefix = f"{path}/"
            stats.total[path] = sum(
                count
                for assigned, count in by_path.items()
                if assigned == path or assigned.startswith(prefix)
            )
        return stats

    async def folder_tag_counts(
        self, *, owner_user_id: str, folder_path: str
    ) -> list[tuple[Tag, int]]:
        in_folder = apply_filters(
            select(ContentObject.id), owner_user_id, NoteFilters(folder_path=folder_path)
        ).where(_is_top_level())
        rows = (
            await self.session.execute(
                select(Tag, func.count(func.distinct(ContentTagAssignment.content_object_id)))
                .join(ContentTagAssignment, ContentTagAssignment.tag_id == Tag.id)
                .where(
                    ContentTagAssignment.status == ACCEPTED_TAG_STATUS,
                    ContentTagAssignment.content_object_id.in_(in_folder.scalar_subquery()),
                )
                .group_by(Tag.id)
            )
        ).all()
        pairs = [(tag, int(count)) for tag, count in rows]
        pairs.sort(key=lambda item: (-item[1], item[0].name.casefold()))
        return pairs
