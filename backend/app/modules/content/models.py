from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ContentCategory(Base):
    __tablename__ = "content_categories"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "path", name="uq_content_categories_owner_user_id_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_categories.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    parent: Mapped[ContentCategory | None] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list[ContentCategory]] = relationship(back_populates="parent")
    objects: Mapped[list[ContentObject]] = relationship(back_populates="category")


class ContentTag(Base):
    __tablename__ = "content_tags"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "slug", name="uq_content_tags_owner_user_id_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255))
    tag_type: Mapped[str] = mapped_column(String(64), default="label")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    objects: Mapped[list[ContentObject]] = relationship(
        secondary="content_object_tags",
        back_populates="tags",
    )


class ContentObjectTag(Base):
    __tablename__ = "content_object_tags"
    __table_args__ = (
        UniqueConstraint("content_object_id", "tag_id", name="uq_content_object_tags_object_tag"),
    )

    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("content_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ContentObject(Base):
    __tablename__ = "content_objects"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "slug", name="uq_content_objects_owner_user_id_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    media_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(2048))
    is_favorite: Mapped[bool] = mapped_column(Boolean(), default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    category: Mapped[ContentCategory | None] = relationship(back_populates="objects")
    tags: Mapped[list[ContentTag]] = relationship(
        secondary="content_object_tags",
        back_populates="objects",
    )
    assets: Mapped[list[ContentAsset]] = relationship(
        back_populates="content_object",
        cascade="all, delete-orphan",
    )
    collection_items: Mapped[list[ContentCollectionItem]] = relationship(
        foreign_keys="ContentCollectionItem.collection_id",
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    collection_memberships: Mapped[list[ContentCollectionItem]] = relationship(
        foreign_keys="ContentCollectionItem.content_object_id",
        back_populates="content_object",
        cascade="all, delete-orphan",
    )


class ContentAsset(Base):
    __tablename__ = "content_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32))
    media_type: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer())
    storage_path: Mapped[str] = mapped_column(String(2048))
    storage_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    storage_ref: Mapped[str | None] = mapped_column(String(2300), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    content_object: Mapped[ContentObject] = relationship(back_populates="assets")


class ContentSource(Base):
    __tablename__ = "content_sources"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_id",
            "content_object_id",
            name="uq_content_sources_provider_external_object",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    content_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_label: Mapped[str] = mapped_column(String(128))
    external_id: Mapped[str] = mapped_column(String(512), index=True)
    group_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    origin: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    author: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    entities: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON(), nullable=True)
    custom_emoji_ids: Mapped[list[str] | None] = mapped_column(JSON(), nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentCollectionItem(Base):
    __tablename__ = "content_collection_items"
    __table_args__ = (
        UniqueConstraint(
            "content_object_id",
            name="uq_content_collection_items_content_object_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer(), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    collection: Mapped[ContentObject] = relationship(
        foreign_keys=[collection_id],
        back_populates="collection_items",
    )
    content_object: Mapped[ContentObject] = relationship(
        foreign_keys=[content_object_id],
        back_populates="collection_memberships",
    )


class ContentFileUpload(Base):
    __tablename__ = "content_file_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_type: Mapped[str] = mapped_column(String(32), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer())
    storage_path: Mapped[str] = mapped_column(String(2048))
    storage_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    storage_ref: Mapped[str | None] = mapped_column(String(2300), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
