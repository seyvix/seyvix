"""Taxonomy worker: event handler (enqueue) and job runner (classification).

Job lifecycle: claim + commit -> load input (short read) -> embedding / LLM judge with no
DB connection held (vector lookup in its own short read) -> finalize in one short
transaction (assignment, job state, change feed).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import EventEnvelope
from app.core.logging import get_logger
from app.modules.content.models import ContentObject
from app.modules.llm.client import AIResponseError, AIUnavailableError, get_ai_client
from app.modules.tags.ai import taxonomy_ai_enabled
from app.modules.taxonomy.classification import (
    ClassificationInput,
    Decision,
    TaxonomyClassifier,
)
from app.modules.taxonomy.infrastructure.repositories import TaxonomyRepository
from app.modules.taxonomy.models import TaxonomyClassificationJob
from app.platform.jobs import JOB_CANCELLED, JOB_PROCESSING, JobQueue
from app.worker.context import WorkerContext

logger = get_logger(__name__)

TAGS_COMPLETED_EVENT = "content.tags.completed"
EVENT_PRIORITY = 100
CANDIDATE_LIMIT = 5


class TaxonomyEventHandler:
    """Enqueues classification once tagging of a note finished (or was skipped)."""

    def __init__(self, session: AsyncSession, ctx: WorkerContext) -> None:
        self.session = session
        self.settings = ctx.settings

    async def handle_event(self, envelope: EventEnvelope) -> None:
        if envelope.event_name != TAGS_COMPLETED_EVENT:
            return
        owner_user_id = envelope.user_id
        content_object_id = str(envelope.payload.get("content_object_id") or envelope.entity_id)
        if owner_user_id is None:
            logger.warning("taxonomy.event.missing_user", event_id=envelope.event_id)
            return
        repository = TaxonomyRepository(self.session)
        if not await repository.content_exists(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        ):
            return
        await repository.enqueue_job(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
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
    final_attempt: bool


@dataclass(frozen=True, slots=True)
class _Decided:
    data: ClassificationInput
    decision: Decision


@dataclass(frozen=True, slots=True)
class _Skipped:
    reason: str
    result_status: str | None = None


@dataclass(frozen=True, slots=True)
class _Failed:
    error: str


_Outcome = _Decided | _Skipped | _Failed


class TaxonomyJobRunner:
    def __init__(self, ctx: WorkerContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        self.queue = JobQueue(
            TaxonomyClassificationJob,
            lease_seconds=ctx.settings.worker_job_lease_seconds,
            worker_id=ctx.worker_id,
        )

    async def run_once(self) -> int:
        async with self.ctx.session_factory() as session:
            jobs = await self.queue.claim(session, limit=self.settings.worker_ai_concurrency)
            claims = [
                _Claim(
                    job.id,
                    job.owner_user_id,
                    job.content_object_id,
                    final_attempt=job.attempts >= job.max_attempts,
                )
                for job in jobs
            ]
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
            logger.error("taxonomy.job.crashed", job_id=claim.job_id, error=str(exc), exc_info=True)
            outcome = _Failed(f"{type(exc).__name__}: {exc}")
        try:
            await self._finalize(claim, outcome)
        except Exception as exc:  # noqa: BLE001 - lease expiry will hand the job out again
            logger.error(
                "taxonomy.job.finalize_failed", job_id=claim.job_id, error=str(exc), exc_info=True
            )

    async def _work(self, claim: _Claim) -> _Outcome:
        ai = get_ai_client(self.settings) if taxonomy_ai_enabled(self.settings) else None
        classifier = TaxonomyClassifier(self.settings, ai)
        async with self.ctx.session_factory() as session:
            data = await classifier.load_input(
                session,
                self.ctx.storage,
                owner_user_id=claim.owner_user_id,
                content_object_id=claim.content_object_id,
            )
        if data is None:
            return _Skipped("Content object no longer exists or is in the trash.")
        if data.user_choice is not None:
            return _Skipped(
                f"Kept the category chosen by the user ({data.user_choice}).",
                result_status="kept_user_choice",
            )
        try:
            decision = await classifier.decide(
                data,
                mode="llm_judge",
                candidate_limit=CANDIDATE_LIMIT,
                read_session=self.ctx.session_factory,
                # Retry while the provider is down; on the last attempt classify without AI.
                allow_degrade=claim.final_attempt,
            )
        except (AIUnavailableError, AIResponseError) as exc:
            logger.warning("taxonomy.job.ai_unavailable", job_id=claim.job_id, error=str(exc))
            return _Failed(f"AI unavailable: {exc}")
        return _Decided(data, decision)

    async def _finalize(self, claim: _Claim, outcome: _Outcome) -> None:
        async with self.ctx.session_factory() as session:
            job = await TaxonomyRepository(session).get_job(claim.job_id, for_update=True)
            if job is None or job.status != JOB_PROCESSING or job.locked_by != self.ctx.worker_id:
                logger.warning("taxonomy.job.lease_lost", job_id=claim.job_id)
                return
            match outcome:
                case _Decided(data, decision):
                    current = await session.scalar(
                        select(ContentObject.updated_at).where(
                            ContentObject.id == claim.content_object_id
                        )
                    )
                    if current is None:
                        _finish_cancelled(job, "Content object no longer exists.")
                    elif current != data.content_updated_at:
                        JobQueue.reset(job)  # edited during classification: redo
                    else:
                        classifier = TaxonomyClassifier(self.settings, None)
                        assignment = await classifier.apply(
                            session, data, decision, respect_user_choice=True
                        )
                        JobQueue.succeed(job)
                        job.assignment_id = assignment.id if assignment is not None else None
                        job.result_status = (
                            decision.status if assignment is not None else "no_assignment"
                        )
                        logger.info(
                            "taxonomy.job.succeeded",
                            job_id=job.id,
                            mode=decision.mode,
                            status=job.result_status,
                        )
                case _Skipped(reason, result_status):
                    if result_status is None:
                        _finish_cancelled(job, reason)
                    else:
                        JobQueue.succeed(job)
                        job.result_status = result_status
                        job.last_error = None
                case _Failed(error):
                    JobQueue.fail(job, error)
            if job.rerun_requested:
                JobQueue.reset(job)
                job.rerun_requested = False
            await session.commit()


def _finish_cancelled(job: TaxonomyClassificationJob, reason: str) -> None:
    job.status = JOB_CANCELLED
    job.last_error = reason
    job.locked_at = None
    job.locked_by = None
