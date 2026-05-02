from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class StorageObject(Base):
    __tablename__ = "storage_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_entity_type: Mapped[str] = mapped_column(String(128), index=True)
    owner_entity_id: Mapped[str] = mapped_column(String(36), index=True)
    storage_backend: Mapped[str] = mapped_column(String(32), index=True)
    bucket: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    storage_ref: Mapped[str] = mapped_column(String(2300))
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer())
    checksum: Mapped[str] = mapped_column(String(128))
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSON(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
