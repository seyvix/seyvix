"""LLM tag suggestions: prompt, structured output and post-filtering of useless tags."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from app.modules.llm.client import AIClient
from app.modules.tags.contracts import ContentTagSuggestion
from app.modules.tags.text import looks_like_filename, slugify_label

PROMPT_VERSION = "content_tags_v2"
MAX_EXCERPT_CHARS = 4000
_MAX_OUTPUT_TOKENS = 1024
# Generic container/format words that are never useful as tags on their own.
_CONTAINER_TAG_SLUGS = frozenset(
    {
        "application",
        "collection",
        "complex",
        "document",
        "file",
        "image",
        "link",
        "page",
        "pdf",
        "simple",
        "text",
    }
)
_PAGE_SLUG_RE = re.compile(r"(page|stranica)-\d+")
_SPLIT_RE = re.compile(r"[\W_]+", re.UNICODE)

SYSTEM_PROMPT = (
    "You suggest concise, useful tags for one item in a personal knowledge base.\n"
    "Only suggest tags supported by the provided title, metadata and text. Cover different "
    "levels of abstraction when the content supports them: broad categories, specific "
    "topics, named entities, technologies, statuses, authors or concepts. Use metadata only "
    "to understand context and provenance; do not tag the source, ingestion channel, "
    "container type, media type, filename, MIME type, extension or format unless the "
    "meaningful text itself is about that subject. Prefer existing candidate tags when they "
    "fit exactly or nearly exactly, and create new tag names when none fit. Write new tags in "
    "the language of the content. Avoid near-duplicates, taxonomy paths and generic labels "
    "like interesting, misc, general or random. Never tag internal metadata values or page "
    "numbers. confidence is your probability (0..1) that the user would keep the tag."
)


class _RawSuggestion(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = Field(default=None, max_length=1000)


class TagSuggestionsOutput(BaseModel):
    tags: list[_RawSuggestion] = Field(default_factory=list)


async def suggest_tags(
    ai: AIClient,
    *,
    model: str,
    title: str,
    url: str | None,
    excerpt: str | None,
    metadata: Mapping[str, object],
    existing_tags: Sequence[str],
    max_tags: int,
) -> list[ContentTagSuggestion]:
    """Ask the model for tags; returns deduplicated suggestions, best first.

    Raises `AIError` subclasses from the client unchanged.
    """
    user_prompt = "\n".join(
        [
            f"Prompt version: {PROMPT_VERSION}",
            f"Maximum tags: {max_tags}",
            f"Title: {title}",
            f"URL: {url or ''}",
            f"Existing candidate tags: {', '.join(existing_tags)}",
            f"Metadata: {json.dumps(dict(metadata), ensure_ascii=False, sort_keys=True)}",
            "Text excerpt:",
            (excerpt or "")[:MAX_EXCERPT_CHARS],
        ]
    )
    output = await ai.chat_json(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        TagSuggestionsOutput,
        model=model,
        temperature=0.0,
        max_tokens=_MAX_OUTPUT_TOKENS,
    )
    blocked = _metadata_only_slugs(title=title, metadata=metadata)
    text_slugs = _text_slugs(excerpt or "") if blocked else frozenset()
    by_slug: dict[str, ContentTagSuggestion] = {}
    for item in output.tags[: max_tags * 2]:
        name = " ".join(item.name.split())
        slug = slugify_label(name)
        if not name or not slug or _PAGE_SLUG_RE.fullmatch(slug):
            continue
        if slug in blocked and slug not in text_slugs:
            continue
        existing = by_slug.get(slug)
        if existing is None or item.confidence > existing.confidence:
            by_slug[slug] = ContentTagSuggestion(
                name=name[:255],
                slug=slug[:255],
                confidence=item.confidence,
                reasoning=item.reasoning,
            )
    ranked = sorted(by_slug.values(), key=lambda suggestion: -suggestion.confidence)
    return ranked[:max_tags]


def _value_slugs(value: str) -> set[str]:
    return {slug for part in _SPLIT_RE.split(value) if (slug := slugify_label(part))}


def _filename_slugs(value: str) -> set[str]:
    filename = value.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0].strip()
    if not filename:
        return set()
    slugs = {slug for slug in (slugify_label(filename),) if slug}
    if "." in filename:
        stem, extension = filename.rsplit(".", 1)
        slugs.update(slug for slug in (slugify_label(stem), slugify_label(extension)) if slug)
        slugs.update(_value_slugs(stem))
    return slugs


def _metadata_only_slugs(*, title: str, metadata: Mapping[str, object]) -> frozenset[str]:
    """Slugs that would only describe the container (format, filename, media type)."""
    slugs = set(_CONTAINER_TAG_SLUGS)
    for key in ("kind", "media_type", "mime_type"):
        value = metadata.get(key)
        if isinstance(value, str):
            slugs.update(_value_slugs(value))
    for value in (title, metadata.get("source_filename")):
        if isinstance(value, str):
            slugs.update(_filename_slugs(value))
    return frozenset(slugs)


def _text_slugs(excerpt: str) -> frozenset[str]:
    """Words of the real text; a container word that the text is about stays allowed."""
    lines = excerpt.splitlines()
    if lines and looks_like_filename(lines[0]):
        lines = lines[1:]
    return frozenset(_value_slugs(" ".join(lines)))
