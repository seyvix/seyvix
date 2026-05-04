from __future__ import annotations

from datetime import datetime
from typing import cast

from app.modules.content.models import (
    ContentAsset,
    ContentCollectionItem,
    ContentFileUpload,
    ContentObject,
    ContentTag,
)
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption


def content_object_load_options() -> tuple[ExecutableOption, ...]:
    return (
        selectinload(ContentObject.tags),
        selectinload(ContentObject.assets),
        selectinload(ContentObject.collection_items)
        .selectinload(ContentCollectionItem.content_object)
        .selectinload(ContentObject.tags),
        selectinload(ContentObject.collection_items)
        .selectinload(ContentCollectionItem.content_object)
        .selectinload(ContentObject.assets),
        selectinload(ContentObject.collection_memberships).selectinload(
            ContentCollectionItem.collection,
        ),
    )


class ContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, content_object: ContentObject) -> None:
        self.session.add(content_object)

    def add_asset(self, asset: ContentAsset) -> None:
        self.session.add(asset)

    def add_collection_item(self, item: ContentCollectionItem) -> None:
        self.session.add(item)

    async def get_by_slug(self, *, owner_user_id: str, slug: str) -> ContentObject | None:
        query = (
            select(ContentObject)
            .options(*content_object_load_options())
            .where(ContentObject.owner_user_id == owner_user_id, ContentObject.slug == slug)
        )
        return cast(ContentObject | None, await self.session.scalar(query))

    async def get_by_id(self, *, owner_user_id: str, object_id: str) -> ContentObject | None:
        query = (
            select(ContentObject)
            .options(*content_object_load_options())
            .where(ContentObject.owner_user_id == owner_user_id, ContentObject.id == object_id)
        )
        return cast(ContentObject | None, await self.session.scalar(query))

    async def get_by_asset_id(
        self,
        *,
        owner_user_id: str,
        asset_id: str,
    ) -> ContentObject | None:
        query = (
            select(ContentObject)
            .options(*content_object_load_options())
            .join(ContentAsset, ContentAsset.content_object_id == ContentObject.id)
            .where(
                ContentObject.owner_user_id == owner_user_id,
                ContentAsset.id == asset_id,
            )
        )
        return cast(ContentObject | None, await self.session.scalar(query))

    async def list_by_slugs(
        self,
        *,
        owner_user_id: str,
        slugs: list[str],
    ) -> list[ContentObject]:
        query = (
            select(ContentObject)
            .options(*content_object_load_options())
            .where(ContentObject.owner_user_id == owner_user_id, ContentObject.slug.in_(slugs))
        )
        return list(await self.session.scalars(query))

    async def slug_exists(self, *, owner_user_id: str, slug: str) -> bool:
        query = select(ContentObject.id).where(
            ContentObject.owner_user_id == owner_user_id,
            ContentObject.slug == slug,
        )
        return await self.session.scalar(query) is not None

    async def lock_slug_base(self, *, owner_user_id: str, slug_base: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"content-object-slug:{owner_user_id}:{slug_base}"},
        )

    async def list_all(self, *, owner_user_id: str) -> list[ContentObject]:
        query = (
            select(ContentObject)
            .options(*content_object_load_options())
            .where(ContentObject.owner_user_id == owner_user_id)
        )
        return list(await self.session.scalars(query))

    async def list_collection_items(self, collection_id: str) -> list[ContentCollectionItem]:
        query = (
            select(ContentCollectionItem)
            .options(
                selectinload(ContentCollectionItem.content_object).selectinload(ContentObject.tags),
                selectinload(ContentCollectionItem.content_object).selectinload(
                    ContentObject.assets,
                ),
                selectinload(ContentCollectionItem.content_object)
                .selectinload(ContentObject.collection_memberships)
                .selectinload(ContentCollectionItem.collection),
            )
            .where(ContentCollectionItem.collection_id == collection_id)
            .order_by(ContentCollectionItem.position.asc())
        )
        return list(await self.session.scalars(query))

    async def get_membership(self, content_object_id: str) -> ContentCollectionItem | None:
        query = select(ContentCollectionItem).where(
            ContentCollectionItem.content_object_id == content_object_id,
        )
        return cast(ContentCollectionItem | None, await self.session.scalar(query))

    async def get_max_sort_order(self, *, owner_user_id: str) -> int:
        objects = await self.list_all(owner_user_id=owner_user_id)
        return max((content_object.sort_order for content_object in objects), default=0)


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, tag: ContentTag) -> None:
        self.session.add(tag)

    async def get_by_slug(self, *, owner_user_id: str, slug: str) -> ContentTag | None:
        query = select(ContentTag).where(
            ContentTag.owner_user_id == owner_user_id,
            ContentTag.slug == slug,
        )
        return cast(ContentTag | None, await self.session.scalar(query))

    async def get_or_create(
        self,
        *,
        owner_user_id: str,
        name: str,
        slug: str,
    ) -> ContentTag:
        statement = (
            postgresql_insert(ContentTag)
            .values(owner_user_id=owner_user_id, name=name, slug=slug)
            .on_conflict_do_nothing(constraint="uq_content_tags_owner_user_id_slug")
            .returning(ContentTag)
        )
        tag = cast(ContentTag | None, await self.session.scalar(statement))
        if tag is not None:
            return tag

        existing = await self.get_by_slug(owner_user_id=owner_user_id, slug=slug)
        if existing is None:
            raise RuntimeError(f"Failed to load content tag after conflict: {slug}")
        return existing

    async def list_all(self, *, owner_user_id: str) -> list[ContentTag]:
        query = (
            select(ContentTag)
            .where(ContentTag.owner_user_id == owner_user_id)
            .order_by(ContentTag.name.asc())
        )
        return list(await self.session.scalars(query))


class FileUploadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, upload: ContentFileUpload) -> None:
        self.session.add(upload)

    async def get_available_by_id(
        self,
        *,
        owner_user_id: str,
        upload_id: str,
    ) -> ContentFileUpload | None:
        query = select(ContentFileUpload).where(
            ContentFileUpload.owner_user_id == owner_user_id,
            ContentFileUpload.id == upload_id,
            ContentFileUpload.consumed_at.is_(None),
        )
        return cast(ContentFileUpload | None, await self.session.scalar(query))

    async def list_expired(
        self,
        *,
        owner_user_id: str,
        now: datetime,
    ) -> list[ContentFileUpload]:
        query = select(ContentFileUpload).where(
            ContentFileUpload.owner_user_id == owner_user_id,
            ContentFileUpload.expires_at <= now,
            ContentFileUpload.consumed_at.is_(None),
        )
        return list(await self.session.scalars(query))
