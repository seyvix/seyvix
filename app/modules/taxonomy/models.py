from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TaxonomyCategory(Base):
    __tablename__ = "taxonomy_categories"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "path", name="uq_taxonomy_categories_owner_path"),
        UniqueConstraint(
            "owner_user_id",
            "parent_id",
            "slug",
            name="uq_taxonomy_categories_owner_parent_slug",
        ),
        CheckConstraint("slug <> ''", name="taxonomy_categories_slug_not_empty"),
        CheckConstraint("name <> ''", name="taxonomy_categories_name_not_empty"),
        CheckConstraint("path <> ''", name="taxonomy_categories_path_not_empty"),
        CheckConstraint("depth >= 0", name="taxonomy_categories_depth_non_negative"),
        Index(
            "uq_taxonomy_categories_owner_root_slug",
            "owner_user_id",
            "slug",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("taxonomy_categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    path: Mapped[str] = mapped_column(String(1024))
    depth: Mapped[int] = mapped_column(Integer(), default=0)
    sort_order: Mapped[int] = mapped_column(Integer(), default=100, index=True)
    source: Mapped[str] = mapped_column(String(32), default="user", index=True)
    is_system: Mapped[bool] = mapped_column(Boolean(), default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean(), default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    parent: Mapped[TaxonomyCategory | None] = relationship(
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list[TaxonomyCategory]] = relationship(back_populates="parent")
    profile: Mapped[TaxonomyCategoryProfile | None] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
    )


class TaxonomyCategoryProfile(Base):
    __tablename__ = "taxonomy_category_profiles"
    __table_args__ = (UniqueConstraint("category_id", name="uq_taxonomy_profiles_category_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    category_id: Mapped[str] = mapped_column(
        ForeignKey("taxonomy_categories.id", ondelete="CASCADE"),
        index=True,
    )
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSON(), default=list)
    positive_examples: Mapped[list[str]] = mapped_column(JSON(), default=list)
    negative_examples: Mapped[list[str]] = mapped_column(JSON(), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    category: Mapped[TaxonomyCategory] = relationship(back_populates="profile")


class TaxonomyContentAssignment(Base):
    __tablename__ = "taxonomy_content_assignments"
    __table_args__ = (
        Index("ix_taxonomy_assignments_owner_content", "owner_user_id", "content_object_id"),
        Index("ix_taxonomy_assignments_owner_category", "owner_user_id", "category_id"),
        Index(
            "uq_taxonomy_assignments_current_content",
            "owner_user_id",
            "content_object_id",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    category_id: Mapped[str] = mapped_column(
        ForeignKey("taxonomy_categories.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text(), nullable=True)
    assigned_by: Mapped[str] = mapped_column(String(32), index=True)
    alternatives: Mapped[list[dict[str, object]]] = mapped_column(JSON(), default=list)
    category_name_snapshot: Mapped[str] = mapped_column(String(255))
    category_path_snapshot: Mapped[str] = mapped_column(String(1024))
    is_current: Mapped[bool] = mapped_column(Boolean(), default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    category: Mapped[TaxonomyCategory] = relationship()


class TaxonomyTemplate(Base):
    __tablename__ = "taxonomy_templates"
    __table_args__ = (UniqueConstraint("slug", name="uq_taxonomy_templates_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    slug: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    categories: Mapped[list[TaxonomyTemplateCategory]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
    )


class TaxonomyTemplateCategory(Base):
    __tablename__ = "taxonomy_template_categories"
    __table_args__ = (
        UniqueConstraint("template_id", "path", name="uq_taxonomy_template_categories_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_id: Mapped[str] = mapped_column(
        ForeignKey("taxonomy_templates.id", ondelete="CASCADE"),
        index=True,
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("taxonomy_template_categories.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    path: Mapped[str] = mapped_column(String(1024))
    depth: Mapped[int] = mapped_column(Integer(), default=0)
    sort_order: Mapped[int] = mapped_column(Integer(), default=100)
    profile_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    profile_keywords: Mapped[list[str]] = mapped_column(JSON(), default=list)
    profile_positive_examples: Mapped[list[str]] = mapped_column(JSON(), default=list)
    profile_negative_examples: Mapped[list[str]] = mapped_column(JSON(), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    template: Mapped[TaxonomyTemplate] = relationship(back_populates="categories")
    parent: Mapped[TaxonomyTemplateCategory | None] = relationship(remote_side=[id])
