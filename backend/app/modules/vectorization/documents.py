"""Build the text to index for a (source, source_type, source_id)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.storage.service import StorageBackend

SOURCE_CONTENT = ("content", "content_object")
SOURCE_TAXONOMY_PROFILE = ("taxonomy", "category_profile")
SUPPORTED_SOURCES = frozenset({SOURCE_CONTENT, SOURCE_TAXONOMY_PROFILE})


class UnsupportedSourceError(ValueError):
    """No document provider for this source type (permanent job failure)."""


def is_supported_source(source: str, source_type: str) -> bool:
    return (source, source_type) in SUPPORTED_SOURCES


async def build_document_text(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    owner_user_id: str,
    source: str,
    source_type: str,
    source_id: str,
    max_chars: int,
) -> str | None:
    """Text to index, or None when the item no longer exists (its index must be removed).

    Tags and taxonomy categories are deliberately NOT part of the indexed text: they change
    after indexing and would force re-embedding; search matches them on live tables instead.
    """
    if (source, source_type) == SOURCE_CONTENT:
        return await _content_object_text(
            session,
            storage,
            owner_user_id=owner_user_id,
            content_object_id=source_id,
            max_chars=max_chars,
        )
    if (source, source_type) == SOURCE_TAXONOMY_PROFILE:
        return await _category_profile_text(
            session, owner_user_id=owner_user_id, category_id=source_id
        )
    raise UnsupportedSourceError(f"No vectorization document provider for {source}/{source_type}.")


async def _content_object_text(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    owner_user_id: str,
    content_object_id: str,
    max_chars: int,
) -> str | None:
    from app.modules.content.text_input import load_content_text_input

    content = await load_content_text_input(
        session,
        storage,
        owner_user_id=owner_user_id,
        content_object_id=content_object_id,
        max_chars=max_chars,
    )
    if content is None:
        return None
    lines = [content.title.strip()]
    if content.url:
        lines.append(content.url.strip())
    if content.text_excerpt and content.text_excerpt.strip():
        lines.extend(["", content.text_excerpt.strip()])
    return "\n".join(lines).strip()


async def _category_profile_text(
    session: AsyncSession, *, owner_user_id: str, category_id: str
) -> str | None:
    from app.modules.taxonomy.errors import TaxonomyNotFoundError
    from app.modules.taxonomy.service import TaxonomyService

    try:
        subject = await TaxonomyService(session).build_category_profile_vector_subject(
            owner_user_id=owner_user_id, category_id=category_id
        )
    except TaxonomyNotFoundError:
        return None
    return subject.source_text.strip()
