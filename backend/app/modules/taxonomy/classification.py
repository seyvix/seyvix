"""Content classification into the user's taxonomy.

Three phases so no DB connection is held during AI calls:

1. `load_input` (short DB read): content text, tags, classifiable categories, user mode.
2. `decide`: candidates from category-profile vectors (query embedding = AI call, vector
   lookup = short DB read) and/or keyword matching against profiles, then optionally an
   LLM judge. Works without AI (keyword candidates + score thresholds).
3. `apply` (short DB write in the caller's transaction) + `build_response`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.content.sync import touch_content_objects
from app.modules.content.text_input import load_content_text_input
from app.modules.llm.client import AIClient, AIResponseError, AIUnavailableError
from app.modules.tags.infrastructure.repositories import TagsRepository
from app.modules.tags.text import match_tokens
from app.modules.taxonomy.contracts import AutomaticApplyMode
from app.modules.taxonomy.infrastructure.repositories import TaxonomyRepository
from app.modules.taxonomy.models import (
    INBOX_PATH,
    TaxonomyCategory,
    TaxonomyContentAssignment,
)
from app.modules.taxonomy.prompts import (
    JUDGE_PROMPT_VERSION,
    JUDGE_SYSTEM_PROMPT,
    CategoryInfo,
    JudgeOutput,
    judge_user_prompt,
)
from app.modules.taxonomy.schemas import (
    TaxonomyClassificationCandidateResponse,
    TaxonomyClassificationCategoryResponse,
    TaxonomyClassificationResponse,
    TaxonomyLLMDecisionResponse,
)
from app.modules.vectorization.api import search_source_vectors
from app.platform.storage.service import StorageBackend

logger = get_logger(__name__)

Mode = Literal["semantic_only", "llm_judge"]
DecisionStatus = Literal["accepted", "proposed", "no_assignment"]
SessionScope = Callable[[], AbstractAsyncContextManager[AsyncSession]]

TEXT_EXCERPT_MAX_CHARS = 4000
MAX_CLASSIFIABLE_CATEGORIES = 2000
_STOPWORDS = frozenset(
    {"type", "content", "object", "title", "tags", "url", "and", "the", "для", "про", "или", "это"}
)


@dataclass(frozen=True, slots=True)
class ClassificationInput:
    owner_user_id: str
    content_object_id: str
    text: str
    content_updated_at: datetime
    apply_mode: AutomaticApplyMode
    categories: tuple[CategoryInfo, ...]  # leaves + inbox, active only
    inbox: CategoryInfo | None
    user_choice: str | None  # path of a non-inbox category the user picked, if any


@dataclass(frozen=True, slots=True)
class Candidate:
    category: CategoryInfo
    score: float
    chunk_id: str


@dataclass(slots=True)
class Decision:
    mode: Mode
    status: DecisionStatus
    target: CategoryInfo | None  # category to assign (None: assign nothing)
    selected: CategoryInfo | None  # best category, shown even when nothing is assigned
    assigned_by: Literal["system", "llm"]
    confidence: float | None
    reasoning: str
    candidates: list[Candidate]
    llm_decision: TaxonomyLLMDecisionResponse | None = None
    alternatives: list[dict[str, object]] = field(default_factory=list)


class TaxonomyClassifier:
    def __init__(self, settings: Settings, ai: AIClient | None) -> None:
        self.settings = settings
        self.ai = ai

    # --- phase 1 -------------------------------------------------------------------------
    async def load_input(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> ClassificationInput | None:
        content = await load_content_text_input(
            session,
            storage,
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            max_chars=TEXT_EXCERPT_MAX_CHARS,
        )
        if content is None:
            return None
        accepted = await TagsRepository(session).list_assignments_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            statuses=("accepted",),
        )
        repository = TaxonomyRepository(session)
        current = await repository.get_current_assignment(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        )
        user_choice = (
            current.category_path_snapshot
            if current is not None
            and current.assigned_by == "user"
            and current.category_path_snapshot != INBOX_PATH
            else None
        )
        categories = await _classifiable_categories(session, owner_user_id=owner_user_id)
        inbox = next((category for category in categories if category.path == INBOX_PATH), None)
        user_settings = await repository.get_settings(owner_user_id=owner_user_id)
        try:
            apply_mode = AutomaticApplyMode(
                user_settings.taxonomy_auto_apply_mode
                if user_settings
                else AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE
            )
        except ValueError:
            apply_mode = AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE
        text = _classification_text(
            title=content.title,
            url=content.url,
            tags=[item.tag.slug for item in accepted],
            metadata=content.metadata,
            excerpt=content.text_excerpt,
        )
        return ClassificationInput(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            text=text,
            content_updated_at=content.updated_at,
            apply_mode=apply_mode,
            categories=tuple(categories),
            inbox=inbox,
            user_choice=user_choice,
        )

    # --- phase 2 -------------------------------------------------------------------------
    async def decide(
        self,
        data: ClassificationInput,
        *,
        mode: Mode,
        candidate_limit: int,
        read_session: SessionScope,
        allow_degrade: bool,
    ) -> Decision:
        """Pick a category. AI failures raise unless `allow_degrade`, in which case the
        decision falls back to keyword/semantic candidates."""
        use_judge = mode == "llm_judge" and self.ai is not None
        semantic = await self._semantic_candidates(
            data, limit=candidate_limit, read_session=read_session, allow_degrade=allow_degrade
        )
        if use_judge:
            candidates = _merge_candidates(
                semantic,
                _textual_candidates(data, limit=candidate_limit),
                limit=max(candidate_limit, min(candidate_limit + 3, 10)),
            )
        else:
            candidates = semantic or _textual_candidates(data, limit=candidate_limit)
        effective_mode: Mode = "llm_judge" if use_judge else "semantic_only"
        if not candidates:
            return self._inbox_decision(
                data,
                effective_mode,
                [],
                confidence=None,
                reasoning="No taxonomy candidates found; assigned to inbox.",
            )
        if not use_judge:
            return self._score_decision(data, effective_mode, candidates, fallback_reason=None)
        try:
            return await self._judge_decision(data, candidates)
        except AIUnavailableError:
            if not allow_degrade:
                raise
            reason = "LLM judge unavailable; fell back to similarity-based classification."
        except AIResponseError as exc:
            reason = f"LLM judge answer unusable; fell back to similarity ranking: {exc}"
        logger.warning("taxonomy.classify.judge_fallback", content_id=data.content_object_id)
        return self._score_decision(data, "llm_judge", candidates, fallback_reason=reason)

    async def _semantic_candidates(
        self,
        data: ClassificationInput,
        *,
        limit: int,
        read_session: SessionScope,
        allow_degrade: bool,
    ) -> list[Candidate]:
        if self.ai is None or not data.categories:
            return []
        try:
            [embedding] = await self.ai.embed([data.text])
        except (AIUnavailableError, AIResponseError):
            if not allow_degrade:
                raise
            logger.warning("taxonomy.classify.embed_failed", content_id=data.content_object_id)
            return []
        async with read_session() as session:
            matches = await search_source_vectors(
                session,
                owner_user_id=data.owner_user_id,
                source="taxonomy",
                source_type="category_profile",
                embedding=embedding,
                limit=limit * 2,
            )
        by_id = {category.id: category for category in data.categories}
        candidates = [
            Candidate(category=by_id[match.source_id], score=match.score, chunk_id=match.chunk_id)
            for match in matches
            if match.source_id in by_id
        ]
        return candidates[:limit]

    async def _judge_decision(
        self, data: ClassificationInput, candidates: list[Candidate]
    ) -> Decision:
        assert self.ai is not None
        keyed = {f"c{index}": candidate for index, candidate in enumerate(candidates, start=1)}
        output = await self.ai.chat_json(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": judge_user_prompt(
                        data.text,
                        [(key, item.category, item.score) for key, item in keyed.items()],
                    ),
                },
            ],
            JudgeOutput,
            model=self.settings.ai_chat_model,
            temperature=0.0,
            max_tokens=768,
        )
        chosen = keyed.get(output.selected_candidate_id or "")
        if output.selected_candidate_id is not None and chosen is None:
            raise AIResponseError(
                f"Judge selected unknown candidate {output.selected_candidate_id!r}."
            )
        llm_decision = TaxonomyLLMDecisionResponse(
            selected_category_id=chosen.category.id if chosen else None,
            confidence=output.confidence,
            should_assign=output.should_assign,
            status=output.status,
            reasoning=output.reasoning,
            alternatives=[
                {
                    "category_id": keyed[item.candidate_id].category.id,
                    "confidence": item.confidence,
                    "reasoning": item.reasoning,
                }
                for item in output.alternatives
                if item.candidate_id in keyed
            ],
        )
        decision = Decision(
            mode="llm_judge",
            status="no_assignment",
            target=None,
            selected=None,
            assigned_by="llm",
            confidence=output.confidence,
            reasoning=output.reasoning,
            candidates=candidates,
            llm_decision=llm_decision,
        )
        if (
            chosen is None
            or not output.should_assign
            or output.status == "no_assignment"
            or output.confidence < self.settings.taxonomy_llm_propose_threshold
        ):
            return decision
        decision.selected = chosen.category
        status = _status_for_mode(
            data.apply_mode, output.confidence, self.settings.taxonomy_llm_accept_threshold
        )
        if status is None:
            decision.reasoning = "Automatic taxonomy classification is disabled for this user."
            return decision
        decision.status = status
        decision.target = chosen.category
        decision.alternatives = [
            {
                "classification_mode": "llm_judge",
                "prompt_version": JUDGE_PROMPT_VERSION,
                "llm_model": self.settings.ai_chat_model,
                "semantic_candidates": [
                    {
                        "category_id": item.category.id,
                        "category_path": item.category.path,
                        "score": item.score,
                        "chunk_id": item.chunk_id,
                    }
                    for item in candidates
                ],
                "llm_decision": llm_decision.model_dump(exclude={"alternatives"}),
            },
            *llm_decision.alternatives,
        ]
        return decision

    def _score_decision(
        self,
        data: ClassificationInput,
        mode: Mode,
        candidates: list[Candidate],
        *,
        fallback_reason: str | None,
    ) -> Decision:
        best = candidates[0]
        if best.score < self.settings.taxonomy_classification_medium_threshold:
            return self._inbox_decision(
                data,
                mode,
                candidates,
                confidence=best.score,
                reasoning=fallback_reason
                or "Similarity was below the assignment threshold; assigned to inbox.",
            )
        status = _status_for_mode(
            data.apply_mode, best.score, self.settings.taxonomy_classification_high_threshold
        )
        if status is None:
            return Decision(
                mode=mode,
                status="no_assignment",
                target=None,
                selected=best.category,
                assigned_by="system",
                confidence=best.score,
                reasoning="Automatic taxonomy classification is disabled for this user.",
                candidates=candidates,
            )
        return Decision(
            mode=mode,
            status=status,
            target=best.category,
            selected=best.category,
            assigned_by="system",
            confidence=best.score,
            reasoning=fallback_reason or "Selected by similarity to taxonomy category profiles.",
            candidates=candidates,
            alternatives=[
                {
                    "category_id": item.category.id,
                    "category_name_snapshot": item.category.name,
                    "category_path_snapshot": item.category.path,
                    "score": item.score,
                    "chunk_id": item.chunk_id,
                }
                for item in candidates
            ],
        )

    @staticmethod
    def _inbox_decision(
        data: ClassificationInput,
        mode: Mode,
        candidates: list[Candidate],
        *,
        confidence: float | None,
        reasoning: str,
    ) -> Decision:
        return Decision(
            mode=mode,
            status="accepted" if data.inbox is not None else "no_assignment",
            target=data.inbox,
            selected=data.inbox,
            assigned_by="system",
            confidence=confidence,
            reasoning=reasoning,
            candidates=candidates,
        )

    # --- phase 3 -------------------------------------------------------------------------
    async def apply(
        self,
        session: AsyncSession,
        data: ClassificationInput,
        decision: Decision,
        *,
        respect_user_choice: bool,
    ) -> TaxonomyContentAssignment | None:
        """Write the decision as the current assignment (no commit). Returns it, or None
        when nothing was assigned. Re-applying the same result does not add history."""
        target = decision.target
        if target is None or decision.status == "no_assignment":
            return None
        repository = TaxonomyRepository(session)
        category = await repository.get_category(
            owner_user_id=data.owner_user_id, category_id=target.id, include_archived=False
        )
        if category is None:
            return None
        current = await repository.get_current_assignment(
            owner_user_id=data.owner_user_id, content_object_id=data.content_object_id
        )
        if (
            respect_user_choice
            and current is not None
            and current.assigned_by == "user"
            and current.category_path_snapshot != INBOX_PATH
        ):
            return None
        if (
            current is not None
            and current.category_id == category.id
            and current.status == decision.status
            and current.assigned_by == decision.assigned_by
        ):
            return current
        return await create_current_assignment(
            session,
            owner_user_id=data.owner_user_id,
            content_object_id=data.content_object_id,
            category=category,
            status=decision.status,
            assigned_by=decision.assigned_by,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            alternatives=decision.alternatives,
        )


def build_response(
    data: ClassificationInput,
    decision: Decision,
    assignment: TaxonomyContentAssignment | None,
    *,
    dry_run: bool,
) -> TaxonomyClassificationResponse:
    would_assign = decision.target is not None and decision.status != "no_assignment"
    return TaxonomyClassificationResponse(
        content_object_id=data.content_object_id,
        mode=decision.mode,
        dry_run=dry_run,
        assigned=assignment is not None,
        assignment_id=assignment.id if assignment is not None else None,
        selected_category=_category_response(decision.selected),
        status=decision.status,
        confidence=decision.confidence,
        reasoning=decision.reasoning,
        semantic_candidates=[
            TaxonomyClassificationCandidateResponse(
                category_id=item.category.id,
                category_name=item.category.name,
                category_path=item.category.path,
                score=item.score,
                chunk_id=item.chunk_id,
            )
            for item in decision.candidates
        ],
        classification_text_preview=data.text[:1000],
        llm_decision=decision.llm_decision,
        would_assign=would_assign,
        would_status=decision.status,
        would_category=_category_response(decision.selected),
    )


async def create_current_assignment(
    session: AsyncSession,
    *,
    owner_user_id: str,
    content_object_id: str,
    category: TaxonomyCategory,
    status: str,
    assigned_by: str,
    confidence: float | None,
    reasoning: str | None,
    alternatives: list[dict[str, object]] | None = None,
) -> TaxonomyContentAssignment:
    """Replace the current assignment of a content object and touch the change feed."""
    await TaxonomyRepository(session).override_current_assignments(
        owner_user_id=owner_user_id, content_object_id=content_object_id
    )
    assignment = TaxonomyContentAssignment(
        owner_user_id=owner_user_id,
        content_object_id=content_object_id,
        category_id=category.id,
        status=status,
        confidence=confidence,
        reasoning=reasoning,
        assigned_by=assigned_by,
        alternatives=alternatives or [],
        category_name_snapshot=category.name,
        category_path_snapshot=category.path,
        is_current=True,
    )
    assignment.category = category
    session.add(assignment)
    await session.flush()
    await touch_content_objects(session, [content_object_id])
    return assignment


# --- helpers -------------------------------------------------------------------------------
async def _classifiable_categories(
    session: AsyncSession, *, owner_user_id: str
) -> list[CategoryInfo]:
    """Active leaf categories (and the inbox) with their profiles, in one round trip."""
    child = aliased(TaxonomyCategory)
    has_active_child = exists().where(
        child.parent_id == TaxonomyCategory.id, child.is_archived.is_(False)
    )
    rows = await session.scalars(
        select(TaxonomyCategory)
        .options(selectinload(TaxonomyCategory.profile))
        .where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            TaxonomyCategory.is_archived.is_(False),
            (TaxonomyCategory.path == INBOX_PATH) | ~has_active_child,
        )
        .order_by(TaxonomyCategory.depth.desc(), TaxonomyCategory.sort_order.asc())
        .limit(MAX_CLASSIFIABLE_CATEGORIES)
    )
    return [category_info(category) for category in rows]


def category_info(category: TaxonomyCategory) -> CategoryInfo:
    profile = category.profile
    return CategoryInfo(
        id=category.id,
        parent_id=category.parent_id,
        name=category.name,
        path=category.path,
        depth=category.depth,
        sort_order=category.sort_order,
        description=category.description,
        summary=profile.summary if profile else None,
        keywords=tuple(profile.keywords) if profile else (),
        positive_examples=tuple(profile.positive_examples) if profile else (),
        negative_examples=tuple(profile.negative_examples) if profile else (),
    )


def _classification_text(
    *,
    title: str,
    url: str | None,
    tags: Sequence[str],
    metadata: dict[str, str | int | bool | None],
    excerpt: str | None,
) -> str:
    """Text used for embedding, keyword matching and the judge prompt.

    Only meaningful metadata is included; timestamps and sizes add noise to embeddings.
    """
    context = {
        key: metadata[key]
        for key in ("kind", "media_type", "source_filename", "mime_type", "source_kind")
        if metadata.get(key) is not None
    }
    lines = [
        f"Title: {title}",
        f"URL: {url or ''}",
        f"Tags: {', '.join(tags)}",
        f"Metadata: {json.dumps(context, ensure_ascii=False, sort_keys=True)}",
        "Content:",
    ]
    if excerpt:
        lines.append(excerpt)
    return "\n".join(lines).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in match_tokens(text, min_length=2) if token not in _STOPWORDS}


def _textual_candidates(data: ClassificationInput, *, limit: int) -> list[Candidate]:
    """Keyword overlap between the content and category names/profiles (no AI needed)."""
    query = _tokens(data.text)
    if not query:
        return []
    scored: list[tuple[float, CategoryInfo]] = []
    for category in data.categories:
        name_tokens = _tokens(f"{category.path.replace('/', ' ')} {category.name}")
        context_tokens = _tokens(f"{category.description or ''} {category.summary or ''}")
        keyword_tokens = _tokens(" ".join(category.keywords))
        positive_tokens = _tokens(" ".join(category.positive_examples))
        name_hits = query & name_tokens
        keyword_hits = query & keyword_tokens
        positive_hits = query & positive_tokens
        if not (name_hits or keyword_hits or positive_hits):
            continue
        signal = name_hits | keyword_hits | positive_hits | (query & context_tokens)
        negative_hits = query & _tokens(" ".join(category.negative_examples))
        if negative_hits and negative_hits >= signal:
            continue
        score = min(
            0.95,
            0.48
            + min(len(name_hits), 3) * 0.05
            + min(len(keyword_hits), 5) * 0.09
            + min(len(positive_hits), 5) * 0.045
            + min(len(query & context_tokens), 4) * 0.012
            + (0.04 if keyword_hits else 0)
            + (0.025 if positive_hits else 0)
            + (0.03 if name_hits else 0)
            + category.depth * 0.02,
        )
        if negative_hits:
            score -= min(0.45, len(negative_hits) * 0.1)
        if score >= 0.5:
            scored.append((score, category))
    scored.sort(key=lambda item: (item[0], item[1].depth, -item[1].sort_order), reverse=True)
    return [
        Candidate(category=category, score=score, chunk_id=f"textual:{category.id}")
        for score, category in scored[:limit]
    ]


def _merge_candidates(
    semantic: list[Candidate], textual: list[Candidate], *, limit: int
) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for candidate in [*semantic, *textual]:
        existing = best.get(candidate.category.id)
        if existing is None or candidate.score > existing.score:
            best[candidate.category.id] = candidate
    return sorted(best.values(), key=lambda item: (item.score, item.category.depth), reverse=True)[
        :limit
    ]


def _status_for_mode(
    mode: AutomaticApplyMode, confidence: float, accept_threshold: float
) -> Literal["accepted", "proposed"] | None:
    if mode == AutomaticApplyMode.DISABLED:
        return None
    if mode == AutomaticApplyMode.MANUAL_REVIEW_ONLY or confidence < accept_threshold:
        return "proposed"
    return "accepted"


def _category_response(
    category: CategoryInfo | None,
) -> TaxonomyClassificationCategoryResponse | None:
    if category is None:
        return None
    return TaxonomyClassificationCategoryResponse(
        id=category.id, name=category.name, path=category.path
    )
