from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.modules.content.models import (
    ContentAsset,
    ContentCollectionItem,
    ContentFileUpload,
    ContentObject,
)


def content_object_load_options() -> tuple[ExecutableOption, ...]:
    """Eager loads needed to render a note card (one query per relationship level)."""
    child = selectinload(ContentObject.collection_items).selectinload(
        ContentCollectionItem.content_object
    )
    return (
        selectinload(ContentObject.assets),
        child.selectinload(ContentObject.assets),
        child.selectinload(ContentObject.collection_items).selectinload(
            ContentCollectionItem.content_object
        ),
        selectinload(ContentObject.collection_memberships).selectinload(
            ContentCollectionItem.collection
        ),
    )


class ContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, content_object: ContentObject) -> None:
        self.session.add(content_object)

    def add_collection_item(self, item: ContentCollectionItem) -> None:
        self.session.add(item)

    def _owned(self, owner_user_id: str, include_deleted: bool) -> Select[tuple[ContentObject]]:
        query = (
            select(ContentObject)
            .options(*content_object_load_options())
            .where(ContentObject.owner_user_id == owner_user_id)
        )
        if not include_deleted:
            query = query.where(ContentObject.deleted_at.is_(None))
        return query

    async def get_by_slug(
        self, *, owner_user_id: str, slug: str, include_deleted: bool = False
    ) -> ContentObject | None:
        query = self._owned(owner_user_id, include_deleted).where(ContentObject.slug == slug)
        return cast(ContentObject | None, await self.session.scalar(query))

    async def get_by_id(
        self, *, owner_user_id: str, object_id: str, include_deleted: bool = False
    ) -> ContentObject | None:
        query = self._owned(owner_user_id, include_deleted).where(ContentObject.id == object_id)
        return cast(ContentObject | None, await self.session.scalar(query))

    async def get_by_asset_id(self, *, owner_user_id: str, asset_id: str) -> ContentObject | None:
        query = self._owned(owner_user_id, False).where(
            ContentObject.id.in_(
                select(ContentAsset.content_object_id).where(ContentAsset.id == asset_id)
            )
        )
        return cast(ContentObject | None, await self.session.scalar(query))

    async def list_by_ids(
        self, *, owner_user_id: str, ids: Sequence[str], include_deleted: bool = False
    ) -> list[ContentObject]:
        if not ids:
            return []
        query = self._owned(owner_user_id, include_deleted).where(ContentObject.id.in_(ids))
        return list(await self.session.scalars(query))

    async def list_by_slugs(
        self, *, owner_user_id: str, slugs: Sequence[str], include_deleted: bool = False
    ) -> list[ContentObject]:
        if not slugs:
            return []
        query = self._owned(owner_user_id, include_deleted).where(ContentObject.slug.in_(slugs))
        return list(await self.session.scalars(query))

    async def slug_exists(self, *, owner_user_id: str, slug: str) -> bool:
        query = select(ContentObject.id).where(
            ContentObject.owner_user_id == owner_user_id, ContentObject.slug == slug
        )
        return await self.session.scalar(query) is not None

    async def lock_slug_base(self, *, owner_user_id: str, slug_base: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"content-object-slug:{owner_user_id}:{slug_base}"},
        )

    async def min_sort_order(self, *, owner_user_id: str) -> int:
        value = await self.session.scalar(
            select(func.min(ContentObject.sort_order)).where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.deleted_at.is_(None),
            )
        )
        return int(value or 0)

    async def next_collection_position(self, collection_id: str) -> int:
        value = await self.session.scalar(
            select(func.max(ContentCollectionItem.position)).where(
                ContentCollectionItem.collection_id == collection_id
            )
        )
        return int(value or 0) + 10

    async def list_collection_items(
        self, collection_id: str, *, include_deleted_children: bool = False
    ) -> list[ContentCollectionItem]:
        query = (
            select(ContentCollectionItem)
            .join(ContentObject, ContentObject.id == ContentCollectionItem.content_object_id)
            .options(
                selectinload(ContentCollectionItem.content_object).options(
                    *content_object_load_options()  # type: ignore[arg-type]
                )
            )
            .where(ContentCollectionItem.collection_id == collection_id)
            .order_by(ContentCollectionItem.position.asc(), ContentCollectionItem.id.asc())
        )
        # Soft-deleted children keep their membership row (restorable from trash) but are
        # hidden from the collection's visible items.
        if not include_deleted_children:
            query = query.where(ContentObject.deleted_at.is_(None))
        return list(await self.session.scalars(query))

    async def get_membership(self, content_object_id: str) -> ContentCollectionItem | None:
        query = select(ContentCollectionItem).where(
            ContentCollectionItem.content_object_id == content_object_id
        )
        return cast(ContentCollectionItem | None, await self.session.scalar(query))

    async def descendant_ids(self, root_ids: Sequence[str]) -> list[str]:
        """`root_ids` plus every object nested (at any depth) in those collections."""
        if not root_ids:
            return []
        roots = select(ContentObject.id.label("id")).where(ContentObject.id.in_(root_ids))
        tree = roots.cte("tree", recursive=True)
        tree = tree.union(
            select(ContentCollectionItem.content_object_id.label("id")).join(
                tree, ContentCollectionItem.collection_id == tree.c.id
            )
        )
        return list(await self.session.scalars(select(tree.c.id)))

    async def live_prefixes(self, prefixes: Sequence[str]) -> set[str]:
        """Which of `prefixes` (`objects/{id}/`) still hold keys of live assets."""
        if not prefixes:
            return set()
        keys = await self.session.scalars(
            select(ContentAsset.storage_key).where(
                or_(*(ContentAsset.storage_key.startswith(p, autoescape=True) for p in prefixes))
            )
        )
        return {prefix for key in keys for prefix in prefixes if key.startswith(prefix)}


class FileUploadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, upload: ContentFileUpload) -> None:
        self.session.add(upload)

    async def list_available(
        self, *, owner_user_id: str, upload_ids: Sequence[str], now: datetime
    ) -> list[ContentFileUpload]:
        if not upload_ids:
            return []
        query = (
            select(ContentFileUpload)
            .where(
                ContentFileUpload.owner_user_id == owner_user_id,
                ContentFileUpload.id.in_(upload_ids),
                ContentFileUpload.expires_at > now,
            )
            .with_for_update()
        )
        return list(await self.session.scalars(query))
