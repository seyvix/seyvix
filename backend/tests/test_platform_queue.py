"""Behavior of the Postgres-backed event and job queues and the worker supervisor."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import String, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.contracts.events import EventEnvelope
from app.contracts.events.routing import CONSUMER_SNAPSHOTS, CONSUMER_TAGS, CONSUMER_VECTORIZATION
from app.platform.events import EventConsumerRunner, EventPublisher, prune_events
from app.platform.events.models import Event, EventDelivery
from app.platform.jobs import (
    JOB_FAILED,
    JOB_PENDING,
    JOB_PROCESSING,
    JOB_SUCCEEDED,
    JobColumnsMixin,
    JobQueue,
    register_notify_triggers,
    utcnow,
)
from app.worker.__main__ import parse_modules
from app.worker.supervisor import Loop, Supervisor


class LocalBase(DeclarativeBase):
    pass


class SampleJob(JobColumnsMixin, LocalBase):
    __tablename__ = "test_sample_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(64))


class HandledEvent(LocalBase):
    __tablename__ = "test_handled_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database.")
    engine = create_async_engine(database_url)
    tables = [Event.__table__, EventDelivery.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(LocalBase.metadata.drop_all)
        await connection.execute(text("DROP TABLE IF EXISTS event_deliveries, events CASCADE"))
        await connection.run_sync(lambda c: Event.metadata.create_all(c, tables=tables))
        await connection.execute(text("DROP FUNCTION IF EXISTS seyvix_notify_job() CASCADE"))
        register_notify_triggers(LocalBase.metadata)
        await connection.run_sync(LocalBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def envelope(name: str = "snapshot.text_representation.completed") -> EventEnvelope:
    return EventEnvelope.new(
        event_name=name,  # type: ignore[arg-type]
        entity_id=str(uuid4()),
        correlation_id=str(uuid4()),
        user_id=str(uuid4()),
        payload={"content_object_id": "x"},
    )


async def publish(factory: async_sessionmaker[AsyncSession], *items: EventEnvelope) -> None:
    async with factory() as session:
        for item in items:
            EventPublisher(session).publish(item)
        await session.commit()


async def delivery_states(
    factory: async_sessionmaker[AsyncSession], consumer: str
) -> list[tuple[str, int]]:
    async with factory() as session:
        rows = await session.execute(
            select(EventDelivery.status, EventDelivery.attempts)
            .where(EventDelivery.consumer == consumer)
            .order_by(EventDelivery.created_at)
        )
        return [(row.status, row.attempts) for row in rows]


class RecordingHandler:
    def __init__(self, session: AsyncSession, *, fail_for: set[str] | None = None) -> None:
        self.session = session
        self.fail_for = fail_for or set()

    async def handle_event(self, item: EventEnvelope) -> None:
        self.session.add(HandledEvent(id=item.event_id))
        await self.session.flush()
        if item.event_id in self.fail_for:
            raise RuntimeError("boom")


async def test_publish_fans_out_one_delivery_per_routed_consumer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await publish(session_factory, envelope(), envelope("taxonomy.classification.completed"))

    async with session_factory() as session:
        consumers = sorted(await session.scalars(select(EventDelivery.consumer)))
        events = await session.scalar(select(func.count()).select_from(Event))

    assert consumers == sorted([CONSUMER_VECTORIZATION, CONSUMER_TAGS])
    assert events == 2  # unrouted events are still recorded


async def test_consumer_commits_handler_writes_atomically_and_isolates_failures(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    good, bad = envelope(), envelope()
    await publish(session_factory, good, bad)
    runner = EventConsumerRunner(
        CONSUMER_TAGS,
        lambda s: RecordingHandler(s, fail_for={bad.event_id}),
        session_factory,
        batch_size=10,
    )

    assert await runner.run_once() == 2

    async with session_factory() as session:
        handled = set(await session.scalars(select(HandledEvent.id)))
        bad_delivery = await session.scalar(
            select(EventDelivery).where(
                EventDelivery.event_id == bad.event_id, EventDelivery.consumer == CONSUMER_TAGS
            )
        )
    assert handled == {good.event_id}  # failed handler's writes rolled back
    assert bad_delivery is not None
    assert bad_delivery.status == JOB_PENDING
    assert bad_delivery.attempts == 1
    assert bad_delivery.run_after > utcnow()  # backoff
    assert "boom" in (bad_delivery.last_error or "")
    # other consumers' queues are untouched
    assert await delivery_states(session_factory, CONSUMER_VECTORIZATION) == [
        (JOB_PENDING, 0),
        (JOB_PENDING, 0),
    ]


async def test_poison_event_becomes_dead_letter_after_max_attempts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bad = envelope()
    await publish(session_factory, bad)
    runner = EventConsumerRunner(
        CONSUMER_TAGS,
        lambda s: RecordingHandler(s, fail_for={bad.event_id}),
        session_factory,
        batch_size=10,
    )
    for _ in range(5):
        async with session_factory() as session:
            await session.execute(update(EventDelivery).values(run_after=utcnow()))
            await session.commit()
        await runner.run_once()

    assert await delivery_states(session_factory, CONSUMER_TAGS) == [(JOB_FAILED, 5)]
    assert await runner.run_once() == 0


async def test_concurrent_consumers_never_process_the_same_delivery(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await publish(session_factory, *(envelope() for _ in range(20)))
    seen: list[str] = []

    class SlowHandler:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def handle_event(self, item: EventEnvelope) -> None:
            seen.append(item.event_id)
            await asyncio.sleep(0.01)

    runners = [
        EventConsumerRunner(CONSUMER_TAGS, SlowHandler, session_factory, batch_size=5)
        for _ in range(4)
    ]
    while sum(await asyncio.gather(*(r.run_once() for r in runners))):
        pass

    assert len(seen) == 20
    assert len(set(seen)) == 20


async def test_prune_keeps_dead_letters_and_unconsumed_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await publish(session_factory, envelope(), envelope("taxonomy.classification.completed"))
    async with session_factory() as session:
        old = utcnow() - timedelta(days=30)
        await session.execute(update(Event).values(created_at=old))
        deliveries = list(await session.scalars(select(EventDelivery)))
        deliveries[0].status = JOB_SUCCEEDED
        deliveries[1].status = JOB_FAILED
        await session.flush()
        await session.execute(update(EventDelivery).values(updated_at=old))
        await session.commit()

        deleted = await prune_events(session, older_than=timedelta(days=7))
        await session.commit()
        remaining_deliveries = list(await session.scalars(select(EventDelivery.status)))
        remaining_events = await session.scalar(select(func.count()).select_from(Event))

    assert deleted == 1  # only the unrouted, fully consumed event
    assert remaining_deliveries == [JOB_FAILED]
    assert remaining_events == 1


async def test_job_queue_claims_by_priority_and_respects_run_after(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                SampleJob(name="low", priority=10),
                SampleJob(name="high", priority=200),
                SampleJob(name="later", priority=500, run_after=utcnow() + timedelta(hours=1)),
            ]
        )
        await session.commit()
    queue = JobQueue(SampleJob, lease_seconds=60, worker_id="w1")

    async with session_factory() as session:
        claimed = await queue.claim(session, limit=10)
        await session.commit()

    assert [job.name for job in claimed] == ["high", "low"]
    assert all(job.status == JOB_PROCESSING and job.attempts == 1 for job in claimed)


async def test_job_queue_reclaims_expired_lease_and_backs_off_failures(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(SampleJob(name="crashy", max_attempts=2))
        await session.commit()
    queue = JobQueue(SampleJob, lease_seconds=60, worker_id="w1")

    async with session_factory() as session:
        [job] = await queue.claim(session, limit=1)
        await session.commit()
    async with session_factory() as session:
        assert await queue.claim(session, limit=1) == []  # lease still valid
        await session.execute(update(SampleJob).values(locked_at=utcnow() - timedelta(seconds=120)))
        [job] = await queue.claim(session, limit=1)  # crashed worker's lease expired
        assert job.attempts == 2
        JobQueue.fail(job, "still broken")
        await session.commit()

    assert job.status == JOB_FAILED  # attempts exhausted

    async with session_factory() as session:
        job = await session.get_one(SampleJob, job.id)
        JobQueue.reset(job)
        await session.commit()
    assert job.status == JOB_PENDING and job.attempts == 0


async def test_supervisor_survives_loop_errors_and_stops_gracefully() -> None:
    calls = 0
    closed = asyncio.Event()

    async def flaky() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return 0

    async def close() -> None:
        closed.set()

    loop = Loop(name="flaky", run_once=flaky, idle_seconds=0.01, close=close)
    supervisor = Supervisor([loop], listen_dsn=None, stop_grace_seconds=1)
    task = asyncio.create_task(supervisor.run())
    loop.wake.set()
    await asyncio.sleep(2.5)  # first failure backs off 2s, then the loop resumes
    supervisor.stop()
    await asyncio.wait_for(task, timeout=3)

    assert calls >= 2
    assert closed.is_set()


async def test_supervisor_wakes_idle_loop_on_job_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    runs = 0
    woke = asyncio.Event()

    async def run_once() -> int:
        nonlocal runs
        runs += 1
        if runs > 2:  # initial run + wake on listener connect, then the NOTIFY wake
            woke.set()
        return 0

    loop = Loop(name="sample", run_once=run_once, tables=("test_sample_jobs",), idle_seconds=60)
    dsn = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    supervisor = Supervisor([loop], listen_dsn=dsn, stop_grace_seconds=1)
    task = asyncio.create_task(supervisor.run())
    await asyncio.sleep(1)  # listener connected, loop idle for 60s
    runs_before = runs
    async with session_factory() as session:
        session.add(SampleJob(name="wake-up"))
        await session.commit()

    await asyncio.wait_for(woke.wait(), timeout=5)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=5)

    assert runs > runs_before


def test_worker_cli_module_selection() -> None:
    assert parse_modules(["snapshots", "tags", "snapshots"]) == ["snapshots", "tags"]
    assert set(parse_modules(["all"])) == {
        "snapshots",
        "vectorization",
        "tags",
        "taxonomy",
        "maintenance",
    }
    with pytest.raises(SystemExit):
        parse_modules(["rabbit"])


def test_routing_contract() -> None:
    from app.contracts.events.routing import EVENT_ROUTES

    assert EVENT_ROUTES["content.object.created"] == (CONSUMER_SNAPSHOTS,)
    assert set(EVENT_ROUTES["snapshot.text_representation.completed"]) == {
        CONSUMER_VECTORIZATION,
        CONSUMER_TAGS,
    }
