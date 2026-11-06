"""Tags worker: event handler (enqueue) and job runner (AI tagging).

Job lifecycle: claim + commit -> load input (short read) -> AI call with no DB connection
held -> finalize in one short transaction (results, job state, change feed, event).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import ContentTagsCompletedPayload, EventEnvelope
from app.core.logging import get_logger
from app.modules.content.models import ContentObject
from app.modules.llm.client import AIResponseError, AIUnavailableError, get_ai_client
from app.modules.tags.ai import tagging_enabled
from app.modules.tags.contracts import ContentTagSuggestion
from app.modules.tags.infrastructure.repositories import TagsRepository
from app.modules.tags.models import TAGGING_JOB_SUGGEST, TaggingJob
from app.modules.tags.suggestions import (
    TaggingInput,
    apply_suggestions,
    generate_suggestions,
    load_tagging_input,
)
from app.platform.events import EventPublisher
from app.platform.jobs import (
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_PROCESSING,
    JOB_SUCCEEDED,
    JobQueue,
)
from app.worker.context import WorkerContext

logger = get_logger(__name__)

TEXT_READY_EVENT = "snapshot.text_representation.completed"
EVENT_PRIORITY = 100


def tags_completed_envelope(
    *,
    owner_user_id: str,
    content_object_id: str,
    correlation_id: str | None,
    status: str,
    job_id: str | None,
) -> EventEnvelope:
    return EventEnvelope.new(
        event_name="content.tags.completed",
        entity_id=content_object_id,
        correlation_id=correlation_id or str(uuid4()),
        user_id=owner_user_id,
        payload=ContentTagsCompletedPayload(
            content_object_id=content_object_id,
            tagging_job_id=job_id,
            job_type=TAGGING_JOB_SUGGEST,
            status=status,
        ),
    )


class TagsEventHandler:
    """Enqueues a tagging job when a note's text becomes available."""

    def __init__(self, session: AsyncSession, ctx: WorkerContext) -> None:
        self.session = session
        self.settings = ctx.settings

    async def handle_event(self, envelope: EventEnvelope) -> None:
        if envelope.event_name != TEXT_READY_EVENT:
            return
        owner_user_id = envelope.user_id
        content_object_id = str(envelope.payload.get("content_object_id") or envelope.entity_id)
        if owner_user_id is None:
            logger.warning("tags.event.missing_user", event_id=envelope.event_id)
            return
        exists = await self.session.scalar(
            select(ContentObject.id).where(
                ContentObject.id == content_object_id,
                ContentObject.owner_user_id == owner_user_id,
            )
        )
        if exists is None:
            return
        if not tagging_enabled(self.settings):
            # Let taxonomy classify (rule-based without AI) even though tagging is off.
            EventPublisher(self.session).publish(
                tags_completed_envelope(
                    owner_user_id=owner_user_id,
                    content_object_id=content_object_id,
                    correlation_id=envelope.correlation_id,
                    status="skipped",
                    job_id=None,
                )
            )
            return
        await TagsRepository(self.session).enqueue_job(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type=TAGGING_JOB_SUGGEST,
            priority=EVENT_PRIORITY,
            max_attempts=self.settings.worker_max_job_attempts,
            source_event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
        )


@dataclass(frozen=True, slots=True)
class _Claim:
    job_id: str
    owner_user_id: str
    content_object_id: str


@dataclass(frozen=True, slots=True)
class _Suggested:
    tagging_input: TaggingInput
    suggestions: list[ContentTagSuggestion]


@dataclass(frozen=True, slots=True)
class _Cancelled:
    reason: str
    notify: bool  # publish content.tags.completed so taxonomy still runs


@dataclass(frozen=True, slots=True)
class _Failed:
    error: str
    retryable: bool = True


_Outcome = _Suggested | _Cancelled | _Failed


class TagsJobRunner:
    def __init__(self, ctx: WorkerContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        self.queue = JobQueue(
            TaggingJob,
            lease_seconds=ctx.settings.worker_job_lease_seconds,
            worker_id=ctx.worker_id,
        )

    async def run_once(self) -> int:
        async with self.ctx.session_factory() as session:
            jobs = await self.queue.claim(session, limit=self.settings.worker_ai_concurrency)
            claims = [_Claim(job.id, job.owner_user_id, job.content_object_id) for job in jobs]
            await session.commit()
        if claims:
            await asyncio.gather(*(self._process(claim) for claim in claims))
        return len(claims)

    async def aclose(self) -> None:
        return None

    async def _process(self, claim: _Claim) -> None:
        try:
            outcome = await self._work(claim)
        except Exception as exc:  # noqa: BLE001 - one bad job must not stop the batch
            logger.error("tags.job.crashed", job_id=claim.job_id, error=str(exc), exc_info=True)
            outcome = _Failed(f"{type(exc).__name__}: {exc}")
        try:
            await self._finalize(claim, outcome)
        except Exception as exc:  # noqa: BLE001 - lease expiry will hand the job out again
            logger.error(
                "tags.job.finalize_failed", job_id=claim.job_id, error=str(exc), exc_info=True
            )

    async def _work(self, claim: _Claim) -> _Outcome:
        ai = get_ai_client(self.settings) if tagging_enabled(self.settings) else None
        if ai is None:
            return _Cancelled("AI tagging is disabled.", notify=True)
        async with self.ctx.session_factory() as session:
            tagging_input = await load_tagging_input(
                session,
                self.ctx.storage,
                owner_user_id=claim.owner_user_id,
                content_object_id=claim.content_object_id,
            )
        if tagging_input is None:
            return _Cancelled("Content object no longer exists or is in the trash.", notify=False)
        try:
            suggestions = await generate_suggestions(
                ai, self.settings, tagging_input, max_tags=self.settings.tags_max_per_note
            )
        except AIUnavailableError as exc:
            logger.warning("tags.job.ai_unavailable", job_id=claim.job_id, error=str(exc))
            return _Failed(f"AI unavailable: {exc}")
        except AIResponseError as exc:
            logger.warning("tags.job.ai_bad_response", job_id=claim.job_id, error=str(exc))
            return _Failed(f"AI response rejected: {exc}")
        return _Suggested(tagging_input, suggestions)

    async def _finalize(self, claim: _Claim, outcome: _Outcome) -> None:
        async with self.ctx.session_factory() as session:
            job = await TagsRepository(session).get_job(claim.job_id, for_update=True)
            if job is None or job.status != JOB_PROCESSING or job.locked_by != self.ctx.worker_id:
                logger.warning("tags.job.lease_lost", job_id=claim.job_id)
                return
            notify = True
            match outcome:
                case _Suggested(tagging_input, suggestions):
                    current = await _content_updated_at(session, claim)
                    if current is None:
                        _cancel(job, "Content object no longer exists.")
                        notify = False
                    elif current != tagging_input.content_updated_at:
                        # Content was edited during the AI call: recompute from fresh text.
                        JobQueue.reset(job)
                    else:
                        changed = await apply_suggestions(
                            session, self.settings, tagging_input, suggestions
                        )
                        JobQueue.succeed(job)
                        logger.info(
                            "tags.job.succeeded",
                            job_id=job.id,
                            suggestions=len(suggestions),
                            changed=changed,
                        )
                case _Cancelled(reason, notify_taxonomy):
                    _cancel(job, reason)
                    notify = notify_taxonomy
                case _Failed(error, retryable):
                    JobQueue.fail(job, error, retryable=retryable)
            if job.rerun_requested:
                JobQueue.reset(job)
                job.rerun_requested = False
            if notify and job.status in (JOB_SUCCEEDED, JOB_FAILED, JOB_CANCELLED):
                EventPublisher(session).publish(
                    tags_completed_envelope(
                        owner_user_id=job.owner_user_id,
                        content_object_id=job.content_object_id,
                        correlation_id=job.correlation_id,
                        status=job.status,
                        job_id=job.id,
                    )
                )
            await session.commit()


def _cancel(job: TaggingJob, reason: str) -> None:
    job.status = JOB_CANCELLED
    job.last_error = reason
    job.locked_at = None
    job.locked_by = None


async def _content_updated_at(session: AsyncSession, claim: _Claim) -> datetime | None:
    updated_at: datetime | None = await session.scalar(
        select(ContentObject.updated_at).where(
            ContentObject.id == claim.content_object_id,
            ContentObject.owner_user_id == claim.owner_user_id,
        )
    )
    return updated_at


__all__ = ["TagsEventHandler", "TagsJobRunner", "tags_completed_envelope"]
