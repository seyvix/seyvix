"""Automatic tag suggestions in three phases so no DB connection is held during AI calls.

1. `load_tagging_input` (short DB read): content text, bounded candidate tags, user mode.
2. `generate_suggestions` (AI only, no DB).
3. `apply_suggestions` (short DB write in the caller's transaction).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.content.sync import touch_content_objects
from app.modules.content.text_input import load_content_text_input
from app.modules.llm.client import AIClient
from app.modules.tags.contracts import ContentTagSuggestion, TagAssignmentStatus
from app.modules.tags.infrastructure.repositories import TagsRepository, index_tags_by_slug
from app.modules.tags.models import ACTIVE_ASSIGNMENT_STATUSES, ContentTagAssignment
from app.modules.tags.tagger import MAX_EXCERPT_CHARS, PROMPT_VERSION, suggest_tags
from app.modules.tags.text import looks_like_filename, match_tokens, strip_filename_heading
from app.modules.taxonomy.contracts import AutomaticApplyMode
from app.modules.taxonomy.models import TaxonomyUserSettings
from app.platform.jobs import utcnow
from app.platform.storage.service import StorageBackend

CANDIDATE_TAG_LIMIT = 24
CANDIDATE_TOKEN_LIMIT = 300


@dataclass(frozen=True, slots=True)
class TaggingInput:
    owner_user_id: str
    content_object_id: str
    title: str
    url: str | None
    excerpt: str | None
    metadata: dict[str, object]
    content_updated_at: datetime
    candidate_tag_names: tuple[str, ...]
    auto_apply_mode: AutomaticApplyMode


async def load_tagging_input(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    owner_user_id: str,
    content_object_id: str,
) -> TaggingInput | None:
    """Everything the model needs. None when the content object is gone or trashed."""
    content = await load_content_text_input(
        session,
        storage,
        owner_user_id=owner_user_id,
        content_object_id=content_object_id,
        max_chars=MAX_EXCERPT_CHARS,
    )
    if content is None:
        return None
    excerpt = strip_filename_heading(content.text_excerpt or "") or None
    semantic_title = None if looks_like_filename(content.title) else content.title
    repository = TagsRepository(session)
    accepted = await repository.list_assignments_for_content(
        owner_user_id=owner_user_id,
        content_object_id=content_object_id,
        statuses=(TagAssignmentStatus.ACCEPTED.value,),
    )
    tokens = [
        token
        for token in match_tokens(
            " ".join(part for part in (semantic_title, excerpt, content.url) if part),
            min_length=3,
            limit=CANDIDATE_TOKEN_LIMIT,
        )
        if not token.isdigit()
    ]
    matches = await repository.candidate_tags(
        owner_user_id=owner_user_id, tokens=tokens, limit=CANDIDATE_TAG_LIMIT
    )
    names = dict.fromkeys([*(item.tag.name for item in accepted), *(tag.name for tag in matches)])
    return TaggingInput(
        owner_user_id=owner_user_id,
        content_object_id=content_object_id,
        title=content.title,
        url=content.url,
        excerpt=excerpt,
        metadata=dict(content.metadata),
        content_updated_at=content.updated_at,
        candidate_tag_names=tuple(list(names)[:CANDIDATE_TAG_LIMIT]),
        auto_apply_mode=await tags_auto_apply_mode(session, owner_user_id=owner_user_id),
    )


async def tags_auto_apply_mode(session: AsyncSession, *, owner_user_id: str) -> AutomaticApplyMode:
    value = await session.scalar(
        select(TaxonomyUserSettings.tags_auto_apply_mode).where(
            TaxonomyUserSettings.owner_user_id == owner_user_id
        )
    )
    try:
        return AutomaticApplyMode(value or AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE)
    except ValueError:
        return AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE


async def generate_suggestions(
    ai: AIClient,
    settings: Settings,
    tagging_input: TaggingInput,
    *,
    max_tags: int,
) -> list[ContentTagSuggestion]:
    suggestions = await suggest_tags(
        ai,
        model=settings.ai_chat_model,
        title=tagging_input.title,
        url=tagging_input.url,
        excerpt=tagging_input.excerpt,
        metadata=tagging_input.metadata,
        existing_tags=tagging_input.candidate_tag_names,
        max_tags=max_tags,
    )
    return [
        suggestion
        for suggestion in suggestions
        if suggestion.confidence >= settings.tags_suggest_threshold
    ][:max_tags]


async def apply_suggestions(
    session: AsyncSession,
    settings: Settings,
    tagging_input: TaggingInput,
    suggestions: Sequence[ContentTagSuggestion],
) -> int:
    """Persist suggestions as suggested/accepted assignments; returns how many changed.

    Never re-suggests a tag the user rejected or removed from this content object.
    Touches the content change feed when anything changed. Does not commit.
    """
    mode = tagging_input.auto_apply_mode
    if mode == AutomaticApplyMode.DISABLED or not suggestions:
        return 0
    owner_user_id = tagging_input.owner_user_id
    content_object_id = tagging_input.content_object_id
    repository = TagsRepository(session)
    slugs = [suggestion.slug for suggestion in suggestions]
    tags_by_slug = index_tags_by_slug(
        await repository.find_tags_by_slugs(owner_user_id=owner_user_id, slugs=slugs)
    )
    source_detail: dict[str, object] = {
        "model": settings.ai_chat_model,
        "prompt_version": PROMPT_VERSION,
    }
    missing = [suggestion for suggestion in suggestions if suggestion.slug not in tags_by_slug]
    if missing and settings.tags_create_missing:
        now = utcnow()
        await repository.insert_missing_tags(
            [
                {
                    "id": str(uuid4()),
                    "owner_user_id": owner_user_id,
                    "name": suggestion.name,
                    "slug": suggestion.slug,
                    "aliases": [],
                    "created_by_type": "llm",
                    "source": "llm_auto_created",
                    "source_detail": source_detail,
                    "confidence": suggestion.confidence,
                    "is_archived": False,
                    "created_at": now,
                    "updated_at": now,
                }
                for suggestion in missing
            ]
        )
        tags_by_slug.update(
            index_tags_by_slug(
                await repository.find_tags_by_slugs(
                    owner_user_id=owner_user_id,
                    slugs=[suggestion.slug for suggestion in missing],
                )
            )
        )

    tag_ids = {tag.id for tag in tags_by_slug.values()}
    history = await _assignment_history(
        session,
        owner_user_id=owner_user_id,
        content_object_id=content_object_id,
        tag_ids=tag_ids,
    )
    changed = 0
    new_rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        tag = tags_by_slug.get(suggestion.slug)
        if tag is None or tag.is_archived or tag.id in seen:
            continue
        seen.add(tag.id)
        status = (
            TagAssignmentStatus.ACCEPTED.value
            if mode == AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE
            and suggestion.confidence >= settings.tags_auto_apply_threshold
            else TagAssignmentStatus.SUGGESTED.value
        )
        previous = history.get(tag.id, [])
        if any(_user_declined(item) for item in previous):
            continue
        active = next(
            (item for item in previous if item.status in ACTIVE_ASSIGNMENT_STATUSES), None
        )
        if active is not None:
            if active.status == TagAssignmentStatus.SUGGESTED.value and status == "accepted":
                active.status = status
                active.source = "llm_auto_applied"
                active.confidence = suggestion.confidence
                active.reasoning = suggestion.reasoning
                changed += 1
            continue
        now = utcnow()
        new_rows.append(
            {
                "id": str(uuid4()),
                "owner_user_id": owner_user_id,
                "content_object_id": content_object_id,
                "tag_id": tag.id,
                "status": status,
                "assigned_by_type": "llm",
                "source": "llm_auto_applied" if status == "accepted" else "llm_suggested",
                "source_detail": source_detail,
                "confidence": suggestion.confidence,
                "reasoning": suggestion.reasoning,
                "created_at": now,
                "updated_at": now,
            }
        )
    if new_rows:
        result = await session.execute(
            pg_insert(ContentTagAssignment)
            .values(new_rows)
            .on_conflict_do_nothing(
                index_elements=[
                    ContentTagAssignment.owner_user_id,
                    ContentTagAssignment.content_object_id,
                    ContentTagAssignment.tag_id,
                ],
                index_where=sql_text("status in ('suggested', 'accepted')"),
            )
        )
        changed += int(getattr(result, "rowcount", 0) or 0)
    if changed:
        await session.flush()
        await touch_content_objects(session, [content_object_id])
    return changed


async def _assignment_history(
    session: AsyncSession,
    *,
    owner_user_id: str,
    content_object_id: str,
    tag_ids: set[str],
) -> dict[str, list[ContentTagAssignment]]:
    if not tag_ids:
        return {}
    rows = await session.scalars(
        select(ContentTagAssignment).where(
            ContentTagAssignment.owner_user_id == owner_user_id,
            ContentTagAssignment.content_object_id == content_object_id,
            ContentTagAssignment.tag_id.in_(tag_ids),
        )
    )
    history: dict[str, list[ContentTagAssignment]] = {}
    for row in rows:
        history.setdefault(row.tag_id, []).append(row)
    return history


def _user_declined(assignment: ContentTagAssignment) -> bool:
    return assignment.assigned_by_type == "user" and assignment.status in {
        TagAssignmentStatus.REJECTED.value,
        TagAssignmentStatus.REMOVED.value,
    }
