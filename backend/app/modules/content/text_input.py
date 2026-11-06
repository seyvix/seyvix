"""Standalone loader of a note's text for AI modules (tags, taxonomy, vectorization).

Depends only on models (no services), so it can be imported anywhere without cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.modules.content.models import ContentObject, ContentSource
from app.modules.content.text import plain_url, telegram_chat_type
from app.modules.snapshots.models import SnapshotArtifact
from app.platform.storage.service import StorageBackend, StorageError

logger = get_logger(__name__)

MetadataValue = str | int | bool | None


@dataclass(frozen=True, slots=True)
class ContentTextInput:
    content_object_id: str
    owner_user_id: str
    title: str
    url: str | None
    text_excerpt: str | None
    metadata: dict[str, MetadataValue]
    created_at: datetime
    updated_at: datetime


async def load_content_text_input(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    owner_user_id: str,
    content_object_id: str,
    max_chars: int = 4000,
) -> ContentTextInput | None:
    content_object = await session.scalar(
        select(ContentObject)
        .options(selectinload(ContentObject.assets))
        .where(
            ContentObject.id == content_object_id,
            ContentObject.owner_user_id == owner_user_id,
            ContentObject.deleted_at.is_(None),
        )
    )
    if content_object is None:
        return None
    source = await session.scalar(
        select(ContentSource)
        .where(
            ContentSource.content_object_id == content_object.id,
            ContentSource.content_asset_id.is_(None),
        )
        .order_by(ContentSource.created_at.asc())
        .limit(1)
    )
    url = (
        content_object.source_filename
        if content_object.media_type == "link"
        and content_object.source_filename
        and plain_url(content_object.source_filename)
        else None
    )
    return ContentTextInput(
        content_object_id=content_object.id,
        owner_user_id=content_object.owner_user_id,
        title=content_object.title,
        url=url,
        text_excerpt=await _text_excerpt(session, storage, content_object, max_chars=max_chars),
        metadata=_metadata(content_object, source),
        created_at=content_object.created_at,
        updated_at=content_object.updated_at,
    )


async def _text_excerpt(
    session: AsyncSession,
    storage: StorageBackend,
    content_object: ContentObject,
    *,
    max_chars: int,
) -> str | None:
    parts: list[str] = []
    size = 0
    missing: list[str] = []
    for asset in content_object.assets:
        if asset.text_content and asset.text_content.strip():
            parts.append(asset.text_content.strip())
            size += len(parts[-1])
        elif asset.media_type != "text":
            missing.append(asset.id)
    if missing and size < max_chars:
        artifacts = await session.scalars(
            select(SnapshotArtifact).where(
                SnapshotArtifact.source_asset_id.in_(missing),
                SnapshotArtifact.artifact_type == "markdown",
            )
        )
        for artifact in artifacts:
            text = await _read_prefix(storage, artifact.storage_key, max_chars=max_chars - size)
            if text:
                parts.append(text)
                size += len(text)
            if size >= max_chars:
                break
    text = "\n\n".join(parts).strip()
    return text[:max_chars] or None


async def _read_prefix(storage: StorageBackend, key: str | None, *, max_chars: int) -> str | None:
    if not key or max_chars <= 0:
        return None
    limit = max_chars * 4  # UTF-8 upper bound
    try:
        data = bytearray()
        async for chunk in storage.iter_bytes(key, 0, limit):
            data.extend(chunk)
    except StorageError:
        logger.warning("content.text_input.artifact_unreadable", key=key)
        return None
    return data.decode("utf-8", errors="ignore").strip()[:max_chars] or None


def _metadata(
    content_object: ContentObject, source: ContentSource | None
) -> dict[str, MetadataValue]:
    origin = source.origin if source is not None and isinstance(source.origin, dict) else {}
    source_title = None
    if source is not None:
        value = source.title or origin.get("title") or origin.get("name") or origin.get("username")
        source_title = str(value) if value else None
    is_telegram = source is not None and source.provider == "telegram"
    author = source.author if source is not None and isinstance(source.author, dict) else {}
    return {
        "kind": content_object.kind,
        "media_type": content_object.media_type,
        "source_filename": content_object.source_filename,
        "mime_type": content_object.mime_type,
        "size_bytes": content_object.size_bytes,
        "is_favorite": content_object.is_favorite,
        "content_created_at": content_object.created_at.isoformat(),
        "content_updated_at": content_object.updated_at.isoformat(),
        "content_source_provider": source.provider if source is not None else None,
        "source_original_created_at": (
            source.original_created_at.isoformat()
            if source is not None and source.original_created_at
            else None
        ),
        "source_kind": str(origin["type"]) if origin.get("type") else None,
        "source_title": source_title,
        "telegram_chat_id": (
            source.external_id.split(":", 1)[0] if source is not None and is_telegram else None
        ),
        "telegram_chat_type": telegram_chat_type(origin) if is_telegram else None,
        "telegram_author_id": (
            str(author["id"]) if is_telegram and author.get("id") is not None else None
        ),
    }
