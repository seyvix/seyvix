from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import Settings
from app.modules.content.storage import slugify
from app.modules.llm.contracts import LLMGenerationError, StructuredLLMGenerator
from app.modules.tags.contracts import ContentTagSuggestion
from pydantic import BaseModel, Field, ValidationError


class LLMTaggingError(Exception):
    pass


_MAX_EXCERPT_CHARS = 4000
_CONTAINER_TAG_SLUGS = {
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


class _RawSuggestion(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None


class _RawTaggingResponse(BaseModel):
    tags: list[_RawSuggestion] = Field(default_factory=list)


class LLMContentTagger:
    def __init__(
        self,
        *,
        settings: Settings,
        llm_generator: StructuredLLMGenerator,
    ) -> None:
        self.settings = settings
        self.llm_generator = llm_generator

    async def suggest(
        self,
        *,
        title: str,
        url: str | None,
        existing_tags: list[str],
        excerpt: str | None,
        metadata: dict[str, object],
        max_tags: int,
    ) -> list[ContentTagSuggestion]:
        prompt = self._build_prompt(
            title=title,
            url=url,
            existing_tags=existing_tags,
            excerpt=excerpt,
            metadata=metadata,
            max_tags=max_tags,
        )
        try:
            raw = await self.llm_generator.generate_structured(
                prompt=prompt,
                schema=self._schema(max_tags=max_tags),
                model_config={
                    "model": self.settings.tags_llm_model,
                    "temperature": 0,
                    "max_tokens": 512,
                },
            )
            parsed = _RawTaggingResponse.model_validate(raw)
        except (LLMGenerationError, ValidationError) as exc:
            raise LLMTaggingError("LLM tag suggestion response is invalid.") from exc

        by_slug: dict[str, ContentTagSuggestion] = {}
        for item in parsed.tags[:max_tags]:
            name = item.name.strip()
            tag_slug = slugify(name)
            if not name or not tag_slug:
                continue
            if self._is_metadata_only_tag(
                name=name,
                slug=tag_slug,
                title=title,
                excerpt=excerpt,
                metadata=metadata,
            ):
                continue
            suggestion = ContentTagSuggestion(
                name=name,
                slug=tag_slug,
                confidence=item.confidence,
                reasoning=item.reasoning,
            )
            existing = by_slug.get(tag_slug)
            if existing is None or suggestion.confidence > existing.confidence:
                by_slug[tag_slug] = suggestion
        return list(by_slug.values())[:max_tags]

    def _build_prompt(
        self,
        *,
        title: str,
        url: str | None,
        existing_tags: list[str],
        excerpt: str | None,
        metadata: dict[str, object],
        max_tags: int,
    ) -> str:
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        trimmed_excerpt = (excerpt or "")[:_MAX_EXCERPT_CHARS]
        existing_tag_text = ", ".join(existing_tags)
        return (
            "Suggest concise, useful tags for one content object.\n"
            "Only suggest tags supported by the provided title, metadata, and text. Cover "
            "different levels of abstraction when the content supports them: broad categories, "
            "specific topics, named entities, technologies, statuses, sources, authors, or "
            "formats. Prefer existing candidate tags when they fit exactly or nearly exactly, "
            "but create new tag names when none of the candidates match the content. Avoid "
            "near-duplicates, taxonomy paths, and generic labels like interesting, misc, "
            "general, or random. Never tag internal metadata values, filenames, page numbers, "
            "file extensions, MIME types, or file formats unless the meaningful text itself is "
            "about them. Return structured JSON only.\n\n"
            f"Maximum tags: {max_tags}\n"
            f"Prompt version: {self.settings.tags_llm_prompt_version}\n"
            f"Title: {title}\n"
            f"URL: {url or ''}\n"
            f"Existing candidate tags: {existing_tag_text}\n"
            f"Metadata: {metadata_json}\n"
            f"Text excerpt:\n{trimmed_excerpt}"
        )

    @classmethod
    def _is_metadata_only_tag(
        cls,
        *,
        name: str,
        slug: str,
        title: str,
        excerpt: str | None,
        metadata: dict[str, object],
    ) -> bool:
        if re.fullmatch(r"page-\d+", slug):
            return True
        if slug not in cls._metadata_only_slugs(title=title, metadata=metadata):
            return False
        meaningful_slugs = cls._meaningful_text_slugs(excerpt or "")
        return slugify(name) not in meaningful_slugs

    @classmethod
    def _metadata_only_slugs(cls, *, title: str, metadata: dict[str, object]) -> set[str]:
        slugs = set(_CONTAINER_TAG_SLUGS)
        for key in ("kind", "media_type", "mime_type"):
            value = metadata.get(key)
            if isinstance(value, str):
                slugs.update(cls._value_slugs(value))

        for value in (title, metadata.get("source_filename")):
            if isinstance(value, str):
                slugs.update(cls._filename_slugs(value))
        return slugs

    @staticmethod
    def _value_slugs(value: str) -> set[str]:
        normalized = value.strip()
        if not normalized:
            return set()
        parts = re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", normalized)
        return {slug for part in parts if (slug := slugify(part))}

    @classmethod
    def _filename_slugs(cls, value: str) -> set[str]:
        filename = value.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0].strip()
        if not filename:
            return set()

        slugs = {slug for slug in {slugify(filename)} if slug}
        if "." not in filename:
            return slugs

        stem, extension = filename.rsplit(".", 1)
        slugs.update(slug for slug in {slugify(stem), slugify(extension)} if slug)
        slugs.update(cls._value_slugs(stem))
        return slugs

    @classmethod
    def _meaningful_text_slugs(cls, excerpt: str) -> set[str]:
        lines = excerpt.splitlines()
        if lines and cls._looks_like_filename_heading(lines[0]):
            lines = lines[1:]
        return cls._value_slugs(" ".join(lines))

    @staticmethod
    def _looks_like_filename_heading(line: str) -> bool:
        text = line.strip().lstrip("#").strip()
        return bool(re.fullmatch(r"[\w .()\-\u0400-\u04FF]+\.[A-Za-z0-9]{1,8}", text))

    @staticmethod
    def _schema(*, max_tags: int) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["tags"],
            "properties": {
                "tags": {
                    "type": "array",
                    "maxItems": max_tags,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "confidence", "reasoning"],
                        "properties": {
                            "name": {"type": "string", "minLength": 1, "maxLength": 255},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reasoning": {"type": ["string", "null"]},
                        },
                    },
                }
            },
        }
