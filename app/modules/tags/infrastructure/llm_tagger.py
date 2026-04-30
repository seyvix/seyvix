from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.modules.content.storage import slugify
from app.modules.llm.contracts import LLMGenerationError, StructuredLLMGenerator
from app.modules.tags.contracts import ContentTagSuggestion


class LLMTaggingError(Exception):
    pass


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
        taxonomy_path: str | None,
        existing_tags: list[str],
        excerpt: str | None,
        metadata: dict[str, object],
        max_tags: int,
    ) -> list[ContentTagSuggestion]:
        prompt = self._build_prompt(
            title=title,
            url=url,
            taxonomy_path=taxonomy_path,
            existing_tags=existing_tags,
            excerpt=excerpt,
            metadata=metadata,
            max_tags=max_tags,
        )
        try:
            raw = await self.llm_generator.generate_structured(
                prompt=prompt,
                schema=self._schema(max_tags=max_tags),
                model_config={"model": self.settings.tags_llm_model, "temperature": 0},
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
        taxonomy_path: str | None,
        existing_tags: list[str],
        excerpt: str | None,
        metadata: dict[str, object],
        max_tags: int,
    ) -> str:
        return (
            "Suggest concise, useful tags for one content object.\n"
            "Prefer concrete labels: entities, technologies, topics, statuses, and filtering "
            "signals. Do not suggest taxonomy paths as tags. Avoid near-duplicates and generic "
            "labels like interesting, misc, general, or random unless they are genuinely useful. "
            "Return structured JSON only.\n\n"
            f"Maximum tags: {max_tags}\n"
            f"Prompt version: {self.settings.tags_llm_prompt_version}\n"
            f"Title: {title}\n"
            f"URL: {url or ''}\n"
            f"Taxonomy category: {taxonomy_path or ''}\n"
            f"Existing tags: {', '.join(existing_tags)}\n"
            f"Metadata: {metadata}\n"
            f"Excerpt:\n{excerpt or ''}\n\n"
            "Good tags: vLLM, KV-cache, latency, benchmark, PostgreSQL, RAG, read-later.\n"
            "Bad tags: interesting, misc, general, AI / LLM / Inference, random."
        )

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
