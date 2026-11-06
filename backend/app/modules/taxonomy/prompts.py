"""LLM prompts and structured-output schemas of the taxonomy module."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

JUDGE_PROMPT_VERSION = "taxonomy_classification_llm_judge_v2"
PROFILE_IMPROVEMENT_PROMPT_VERSION = "taxonomy_profile_improvement_v1"


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    """Detached snapshot of a category and its profile (safe across sessions)."""

    id: str
    parent_id: str | None
    name: str
    path: str
    depth: int
    sort_order: int
    description: str | None
    summary: str | None
    keywords: tuple[str, ...]
    positive_examples: tuple[str, ...]
    negative_examples: tuple[str, ...]


# --- classification judge ------------------------------------------------------------------
class JudgeAlternative(BaseModel):
    candidate_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: str = ""


class JudgeOutput(BaseModel):
    selected_candidate_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    should_assign: bool
    status: Literal["accepted", "proposed", "no_assignment"]
    reasoning: str = Field(max_length=2000)
    alternatives: list[JudgeAlternative] = Field(default_factory=list, max_length=10)


JUDGE_SYSTEM_PROMPT = "\n".join(
    [
        f"prompt_version = {JUDGE_PROMPT_VERSION}",
        "You are a taxonomy classification judge for a personal knowledge base.",
        "Choose only from the provided candidates, by their candidate_id (e.g. c1).",
        "Do not invent, rename or move categories.",
        "Prefer the deepest specific category when it clearly fits; prefer a broader one only "
        "if the specific candidate is too narrow.",
        "Treat negative_examples as exclusion rules, not supporting evidence. If the content "
        "mainly resembles a candidate's negative_examples, do not choose it.",
        "Return should_assign = false if none of the candidates fit.",
        "Use score as a signal, not as the only decision factor.",
        "confidence is your probability (0..1) that the chosen category is right.",
        "Explain briefly why the selected category fits.",
    ]
)


def judge_user_prompt(
    content_text: str, candidates: Sequence[tuple[str, CategoryInfo, float]]
) -> str:
    lines = ["Content:", content_text, "", "Candidates:"]
    for candidate_id, category, score in candidates:
        lines.extend(
            [
                f"- candidate_id: {candidate_id}",
                f"  path: {category.path}",
                f"  name: {category.name}",
                f"  description: {category.description or ''}",
                f"  profile_summary: {category.summary or ''}",
                f"  keywords: {', '.join(category.keywords)}",
                f"  positive_examples: {'; '.join(category.positive_examples)}",
                f"  negative_examples: {'; '.join(category.negative_examples)}",
                f"  score: {score:.3f}",
            ]
        )
    return "\n".join(lines)


# --- profile improvement -------------------------------------------------------------------
class ProfileDraftOutput(BaseModel):
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list, max_length=20)
    positive_examples: list[str] = Field(default_factory=list, max_length=20)
    negative_examples: list[str] = Field(default_factory=list, max_length=20)
    reasoning: str = Field(min_length=1, max_length=2000)


PROFILE_SYSTEM_PROMPT = "\n".join(
    [
        f"prompt_version = {PROFILE_IMPROVEMENT_PROMPT_VERSION}",
        "You improve taxonomy category profiles for a personal knowledge base.",
        "Return a draft only. Do not save or apply changes.",
        "Keep the category boundary practical for classification.",
        "Write summaries, keywords and examples in English, even when the user guidance is "
        "not English.",
        "Use negative examples only for exclusion boundaries; do not repeat likely positive "
        "retrieval terms there unless needed to prevent a common mistake.",
        "Make summary, keywords, positive and negative examples directly useful for future "
        "automatic classification.",
    ]
)


def profile_user_prompt(
    category: CategoryInfo, children: Sequence[CategoryInfo], user_guidance: str
) -> str:
    return "\n".join(
        [
            "Category:",
            f"Category path: {category.path}",
            f"Category name: {category.name}",
            f"Category description: {category.description or ''}",
            "",
            "Current profile:",
            f"Summary: {category.summary or ''}",
            f"Keywords: {', '.join(category.keywords)}",
            f"Positive examples: {' | '.join(category.positive_examples)}",
            f"Negative examples: {' | '.join(category.negative_examples)}",
            "",
            "Child categories:",
            *[f"- {child.path}: {child.description or child.name}" for child in children],
            "",
            "User guidance:",
            user_guidance,
        ]
    )


# --- onboarding from free-text interests ---------------------------------------------------
class InterestChild(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class InterestNode(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    children: list[InterestChild] = Field(default_factory=list, max_length=8)


class InterestTreeOutput(BaseModel):
    categories: list[InterestNode] = Field(min_length=1, max_length=6)


INTEREST_SYSTEM_PROMPT = (
    "Create a concise personal knowledge taxonomy from the user's interests. Return 3-6 "
    "top-level categories with up to 4 useful children each. Use short, specific category "
    "names that will work as stable navigation labels. Make categories non-overlapping: each "
    "note should have one obvious best category. Avoid generic labels like Misc, Other, "
    "Useful, Notes or Inbox. Prefer the user's language."
)


def interest_user_prompt(custom_description: str) -> str:
    return f"User interests:\n{custom_description[:2000]}"
