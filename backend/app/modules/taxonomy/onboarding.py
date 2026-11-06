"""Initial taxonomy from interest presets (JSON templates) or a free-text description."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.llm.client import AIClient, AIError
from app.modules.tags.ai import INTERACTIVE_AI_TIMEOUT_SECONDS
from app.modules.tags.text import slugify_label
from app.modules.taxonomy.errors import TaxonomyValidationError
from app.modules.taxonomy.models import INBOX_PATH, TaxonomyCategory, TaxonomyCategoryProfile
from app.modules.taxonomy.prompts import (
    INTEREST_SYSTEM_PROMPT,
    InterestTreeOutput,
    interest_user_prompt,
)
from app.modules.vectorization.api import enqueue_vectorization

logger = get_logger(__name__)

INTEREST_SPECS_DIR = Path(__file__).with_name("templates") / "interests"
INTEREST_SPEC_SLUGS = (
    "ai",
    "software",
    "tools",
    "creative",
    "media",
    "learning",
    "gear",
    "work",
    "life",
)
CATEGORY_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
_NON_CATEGORY_SLUG_RE = re.compile(r"[^a-z0-9_-]+")

TemplateNode = dict[str, object]


@dataclass(frozen=True, slots=True)
class InterestOption:
    slug: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class InitializeTaxonomyResult:
    owner_user_id: str
    template_slug: str
    created_categories_count: int
    created_profiles_count: int


def category_slug(name: str) -> str:
    """Category path segment for a label; non-Latin scripts get a stable hashed slug."""
    slug = _NON_CATEGORY_SLUG_RE.sub("-", slugify_label(name)).strip("-")
    if slug:
        return slug[:255]
    if not name.strip():
        raise TaxonomyValidationError
    return "c-" + hashlib.sha1(name.strip().casefold().encode("utf-8")).hexdigest()[:10]


# --- presets -------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def interest_specs() -> dict[str, dict[str, object]]:
    """Validated interest presets, read from disk once per process."""
    return {slug: _load_interest_spec(slug) for slug in INTEREST_SPEC_SLUGS}


@lru_cache(maxsize=1)
def interest_specs_by_slug() -> dict[str, dict[str, object]]:
    specs: dict[str, dict[str, object]] = {}
    for slug, spec in interest_specs().items():
        specs[slug] = spec
        for alias in cast(list[str], spec.get("aliases", [])):
            if alias.strip():
                specs[alias.strip()] = spec
    return specs


def list_interest_options() -> list[InterestOption]:
    return [
        InterestOption(slug=slug, name=str(spec["name"]), description=str(spec["description"]))
        for slug, spec in interest_specs().items()
    ]


def _load_interest_spec(slug: str) -> dict[str, object]:
    try:
        raw = json.loads((INTEREST_SPECS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaxonomyValidationError(f"Interest preset {slug} is unreadable.") from exc
    if not isinstance(raw, dict) or raw.get("slug") != slug:
        raise TaxonomyValidationError(f"Interest preset {slug} is malformed.")
    spec = cast(dict[str, object], raw)
    for field_name in ("name", "description"):
        if not isinstance(spec.get(field_name), str) or not str(spec[field_name]).strip():
            raise TaxonomyValidationError(f"Interest preset {slug} lacks {field_name}.")
    aliases = spec.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
        raise TaxonomyValidationError(f"Interest preset {slug} has invalid aliases.")
    tree = spec.get("tree")
    if not isinstance(tree, list):
        raise TaxonomyValidationError(f"Interest preset {slug} has no tree.")
    _validate_template_nodes(cast(list[object], tree))
    return spec


def _validate_template_nodes(nodes: list[object]) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            raise TaxonomyValidationError
        item = cast(TemplateNode, node)
        if not isinstance(item.get("name"), str) or not str(item["name"]).strip():
            raise TaxonomyValidationError
        if "description" in item and not isinstance(item["description"], str):
            raise TaxonomyValidationError
        if "profile" in item and not isinstance(item["profile"], dict):
            raise TaxonomyValidationError
        children = item.get("children", [])
        if not isinstance(children, list):
            raise TaxonomyValidationError
        _validate_template_nodes(cast(list[object], children))


# --- profiles ------------------------------------------------------------------------------
def default_profile(name: str) -> dict[str, object]:
    return {
        "summary": (
            f"Materials where {name} is the primary topic, task, or decision area. "
            "Use this category for notes, links, and files that should be found later "
            "because of this topic, not because it is mentioned in passing."
        ),
        "keywords": list(dict.fromkeys([category_slug(name), name.strip().casefold()])),
        "positive_examples": [
            f"A note, link, or file where {name} is the main subject.",
            f"Material with decisions, examples, tools, or sources about {name}.",
            f"A working note that should later be searched through {name}.",
        ],
        "negative_examples": [
            f"A passing mention of {name} without useful content about the topic.",
            "A general note that clearly belongs to a more specific category.",
            "Material where this category is only the file format, source, or context.",
        ],
    }


def profile_for_new_category(
    category: TaxonomyCategory, *, profile_source: str
) -> TaxonomyCategoryProfile:
    """Starter profile for a category created by hand or from a path."""
    profile = default_profile(category.name)
    path_parts = category.path.split("/")
    summary = str(profile["summary"])
    if len(path_parts) > 1:
        parent_hint = path_parts[-2].replace("-", " ")
        summary = (
            f"{summary} Boundary: classify content here only when {category.name} "
            f"is relevant within {parent_hint}, not for every generic mention of similar words."
        )
    return TaxonomyCategoryProfile(
        category_id=category.id,
        summary=summary,
        keywords=list(dict.fromkeys([*cast(list[str], profile["keywords"]), *path_parts])),
        positive_examples=cast(list[str], profile["positive_examples"]),
        negative_examples=cast(list[str], profile["negative_examples"]),
        profile_source=profile_source,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _template_profile(name: str, node: TemplateNode) -> dict[str, object]:
    profile = node.get("profile")
    if not isinstance(profile, dict):
        return default_profile(name)
    data = cast(dict[str, object], profile)
    result: dict[str, object] = {
        "summary": str(data.get("summary") or "").strip(),
        "keywords": _string_list(data.get("keywords")),
        "positive_examples": _string_list(data.get("positive_examples")),
        "negative_examples": _string_list(data.get("negative_examples")),
    }
    return result if all(result.values()) else default_profile(name)


def _node(name: str, children: list[TemplateNode] | None = None) -> TemplateNode:
    return {"name": name, "children": children or []}


def flatten_template_tree(tree: list[TemplateNode]) -> list[TemplateNode]:
    flattened: list[TemplateNode] = []

    def visit(nodes: list[TemplateNode], parent_path: str, depth: int, generated: bool) -> None:
        for index, node in enumerate(nodes):
            name = str(node["name"]).strip()
            slug = category_slug(name)
            path = f"{parent_path}/{slug}".strip("/")
            flattened.append(
                {
                    "slug": slug,
                    "name": name,
                    "description": str(node.get("description") or f"Materials related to {name}."),
                    "path": path,
                    "depth": depth,
                    "sort_order": index * 10,
                    "profile": _template_profile(name, node),
                    "generated": generated or bool(node.get("generated")),
                }
            )
            visit(
                cast(list[TemplateNode], node.get("children", [])),
                path,
                depth + 1,
                generated or bool(node.get("generated")),
            )

    visit(tree, "", 0, False)
    return flattened


# --- initialization ------------------------------------------------------------------------
def build_interest_tree(interest_slugs: list[str]) -> list[TemplateNode]:
    presets = interest_specs_by_slug()
    if any(slug not in presets for slug in interest_slugs):
        raise TaxonomyValidationError
    tree = [_node("Inbox")]
    for slug in interest_slugs:
        tree.extend(cast(list[TemplateNode], presets[slug]["tree"]))
    return tree


async def custom_interest_tree(
    ai: AIClient | None, settings: Settings, custom_description: str
) -> list[TemplateNode]:
    """Tree generated from a free-text description; a generic tree if AI is unavailable."""
    if ai is not None:
        try:
            async with asyncio.timeout(INTERACTIVE_AI_TIMEOUT_SECONDS):
                output = await ai.chat_json(
                    [
                        {"role": "system", "content": INTEREST_SYSTEM_PROMPT},
                        {"role": "user", "content": interest_user_prompt(custom_description)},
                    ],
                    InterestTreeOutput,
                    model=settings.ai_chat_model,
                    temperature=0.2,
                    max_tokens=900,
                )
            return [
                _node(node.name, [_node(child.name) for child in node.children[:8]])
                | {"generated": True}
                for node in output.categories[:6]
            ]
        except (AIError, TimeoutError) as exc:
            logger.warning("taxonomy.onboarding.ai_failed", error=str(exc) or "timeout")
    return [
        _node("Custom Interests", [_node("Research"), _node("Projects"), _node("Learning")])
        | {
            "description": f"User-described interests: {custom_description[:500]}",
            "generated": True,
        }
    ]


async def create_categories_from_tree(
    session: AsyncSession, *, owner_user_id: str, tree: list[TemplateNode]
) -> tuple[int, int]:
    """Insert the flattened tree with profiles and queue profile indexing. No commit.

    Returns (categories created, profiles created).
    """
    created: dict[str, TaxonomyCategory] = {}
    for item in flatten_template_tree(tree):
        path = str(item["path"])
        if path in created:
            continue
        parent_path = path.rsplit("/", 1)[0] if "/" in path else None
        parent = created.get(parent_path) if parent_path is not None else None
        is_inbox = path == INBOX_PATH
        category = TaxonomyCategory(
            id=str(uuid4()),
            owner_user_id=owner_user_id,
            parent_id=parent.id if parent is not None else None,
            slug=str(item["slug"]),
            name=str(item["name"]),
            description=str(item["description"]),
            path=path,
            depth=cast(int, item["depth"]),
            sort_order=cast(int, item["sort_order"]),
            source="system" if is_inbox else "onboarding",
            is_system=is_inbox,
        )
        profile = cast(dict[str, object], item["profile"])
        session.add(category)
        session.add(
            TaxonomyCategoryProfile(
                category_id=category.id,
                summary=str(profile["summary"]),
                keywords=cast(list[str], profile["keywords"]),
                positive_examples=cast(list[str], profile["positive_examples"]),
                negative_examples=cast(list[str], profile["negative_examples"]),
                profile_source="llm_generated" if item["generated"] else "template",
            )
        )
        created[path] = category
    await session.flush()
    for category in created.values():
        await enqueue_vectorization(
            session,
            owner_user_id=owner_user_id,
            source="taxonomy",
            source_type="category_profile",
            source_id=category.id,
        )
    return len(created), len(created)
