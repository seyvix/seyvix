"""Worker modules: each one can run in its own process/container or together with others.

Module code is imported lazily so a process only loads (and needs the system deps of) the
modules it actually runs — e.g. the light worker never imports Playwright.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from app.contracts.events.routing import (
    CONSUMER_SNAPSHOTS,
    CONSUMER_TAGS,
    CONSUMER_TAXONOMY,
    CONSUMER_VECTORIZATION,
)
from app.platform.events import EventConsumerRunner, EventHandlerFactory, prune_events
from app.platform.heartbeat import prune_heartbeats
from app.worker.context import JobRunner, WorkerContext
from app.worker.supervisor import Loop


def _consumer_loop(ctx: WorkerContext, consumer: str, factory: EventHandlerFactory) -> Loop:
    runner = EventConsumerRunner(
        consumer, factory, ctx.session_factory, batch_size=ctx.settings.outbox_batch_size
    )
    return Loop(
        name=f"{consumer}.events",
        run_once=runner.run_once,
        tables=("event_deliveries",),
        idle_seconds=ctx.settings.worker_idle_poll_seconds,
    )


def _job_loop(ctx: WorkerContext, name: str, runner: JobRunner, table: str) -> Loop:
    return Loop(
        name=f"{name}.jobs",
        run_once=runner.run_once,
        tables=(table,),
        idle_seconds=ctx.settings.worker_idle_poll_seconds,
        close=runner.aclose,
    )


def snapshots(ctx: WorkerContext) -> list[Loop]:
    from app.modules.snapshots.worker import SnapshotEventHandler, SnapshotJobRunner

    return [
        _consumer_loop(ctx, CONSUMER_SNAPSHOTS, lambda s: SnapshotEventHandler(s, ctx)),
        _job_loop(ctx, "snapshots", SnapshotJobRunner(ctx), "snapshot_jobs"),
    ]


def vectorization(ctx: WorkerContext) -> list[Loop]:
    from app.modules.vectorization.worker import (
        VectorizationEventHandler,
        VectorizationJobRunner,
    )

    return [
        _consumer_loop(ctx, CONSUMER_VECTORIZATION, lambda s: VectorizationEventHandler(s, ctx)),
        _job_loop(ctx, "vectorization", VectorizationJobRunner(ctx), "vectorization_jobs"),
    ]


def tags(ctx: WorkerContext) -> list[Loop]:
    from app.modules.tags.worker import TagsEventHandler, TagsJobRunner

    return [
        _consumer_loop(ctx, CONSUMER_TAGS, lambda s: TagsEventHandler(s, ctx)),
        _job_loop(ctx, "tags", TagsJobRunner(ctx), "tagging_jobs"),
    ]


def taxonomy(ctx: WorkerContext) -> list[Loop]:
    from app.modules.taxonomy.worker import TaxonomyEventHandler, TaxonomyJobRunner

    return [
        _consumer_loop(ctx, CONSUMER_TAXONOMY, lambda s: TaxonomyEventHandler(s, ctx)),
        _job_loop(ctx, "taxonomy", TaxonomyJobRunner(ctx), "taxonomy_classification_jobs"),
    ]


def maintenance(ctx: WorkerContext) -> list[Loop]:
    """Periodic housekeeping. Run it in exactly one process."""
    from app.modules.content.maintenance import run_content_maintenance

    async def run_once() -> int:
        async with ctx.session_factory() as session:
            await prune_events(
                session, older_than=timedelta(days=ctx.settings.outbox_retention_days)
            )
            await prune_heartbeats(session, older_than=timedelta(days=1))
            await session.commit()
        await run_content_maintenance(ctx)
        return 0  # always idle until the next interval

    return [
        Loop(
            name="maintenance",
            run_once=run_once,
            idle_seconds=float(ctx.settings.maintenance_interval_seconds),
        )
    ]


MODULES: dict[str, Callable[[WorkerContext], list[Loop]]] = {
    "snapshots": snapshots,
    "vectorization": vectorization,
    "tags": tags,
    "taxonomy": taxonomy,
    "maintenance": maintenance,
}
