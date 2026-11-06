from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ContentObject(Base):
    """A note: simple (one asset), complex (several assets) or a collection of notes."""

    __tablename__ = "content_objects"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "slug", name="uq_content_objects_owner_user_id_slug"),
        # Dashboard listing (newest first / custom order) of live notes.
        Index(
            "ix_content_objects_owner_live_created",
            "owner_user_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_content_objects_owner_live_sort",
            "owner_user_id",
            "sort_order",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_content_objects_owner_trash",
            "owner_user_id",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
        Index(
            "ix_content_objects_trash_purge",
            "delete_after",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
        # Change feed: `WHERE owner_user_id = ? AND changed_at > ? ORDER BY changed_at`.
        Index("ix_content_objects_owner_changed", "owner_user_id", "changed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(32))
    media_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean(), default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Bumped (see `app.modules.content.sync`) whenever anything that affects how the note
    # renders changes: edits, snapshots, tags, taxonomy, trash/restore, collection moves.
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()")
    )

    assets: Mapped[list[ContentAsset]] = relationship(
        back_populates="content_object",
        cascade="all, delete-orphan",
        order_by="ContentAsset.created_at",
    )
    collection_items: Mapped[list[ContentCollectionItem]] = relationship(
        foreign_keys="ContentCollectionItem.collection_id",
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="ContentCollectionItem.position",
    )
    collection_memberships: Mapped[list[ContentCollectionItem]] = relationship(
        foreign_keys="ContentCollectionItem.content_object_id",
        back_populates="content_object",
        cascade="all, delete-orphan",
    )


class ContentAsset(Base):
    __tablename__ = "content_assets"
    __table_args__ = (
        # Prefix lookups (`storage_key LIKE 'objects/<id>/%'`) for safe storage cleanup.
        Index(
            "ix_content_assets_storage_key_prefix",
            "storage_key",
            postgresql_ops={"storage_key": "varchar_pattern_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    media_type: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer())
    # Never rewritten when an asset moves between objects (merge/collapse), so the key's
    # `objects/{id}/` prefix may name a different object than `content_object_id`.
    storage_key: Mapped[str] = mapped_column(String(1024))
    checksum: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    content_object: Mapped[ContentObject] = relationship(back_populates="assets")


class ContentLinkSnapshotDecision(Base):
    __tablename__ = "content_link_snapshot_decisions"

    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"), primary_key=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContentSource(Base):
    __tablename__ = "content_sources"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_id",
            "content_object_id",
            name="uq_content_sources_provider_external_object",
        ),
        Index("ix_content_sources_owner_provider", "owner_user_id", "provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"), index=True
    )
    content_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(64))
    provider_label: Mapped[str] = mapped_column(String(128))
    external_id: Mapped[str] = mapped_column(String(512))
    group_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        UniqueConstraint("content_object_id", name="uq_content_collection_items_content_object_id"),
        Index("ix_content_collection_items_collection_position", "collection_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    collection_id: Mapped[str] = mapped_column(ForeignKey("content_objects.id", ondelete="CASCADE"))
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer(), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    collection: Mapped[ContentObject] = relationship(
        foreign_keys=[collection_id], back_populates="collection_items"
    )
    content_object: Mapped[ContentObject] = relationship(
        foreign_keys=[content_object_id], back_populates="collection_memberships"
    )


class ContentFileUpload(Base):
    """A file uploaded ahead of note creation (two-step upload flow)."""

    __tablename__ = "content_file_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer())
    storage_key: Mapped[str] = mapped_column(String(1024))
    checksum: Mapped[str | None] = mapped_column(String(80), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentTombstone(Base):
    """Hard-deleted note ids, kept briefly so the change feed can report removals."""

    __tablename__ = "content_tombstones"
    __table_args__ = (Index("ix_content_tombstones_owner_deleted", "owner_user_id", "deleted_at"),)

    content_object_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
