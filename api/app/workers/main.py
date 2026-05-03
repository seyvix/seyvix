from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.contracts.events import EventEnvelope
from app.core.config import get_settings
from app.core.database import build_session_factory
from app.core.logging import configure_logging, get_logger
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.content import models as content_models  # noqa: F401
from app.modules.snapshots import models as snapshot_models  # noqa: F401
from app.modules.snapshots.worker import SnapshotWorker
from app.modules.tags import models as tags_models  # noqa: F401
from app.modules.tags.worker import TagsEventConsumer, TagsWorker
from app.modules.taxonomy import models as taxonomy_models  # noqa: F401
from app.modules.taxonomy.worker import TaxonomyEventConsumer, TaxonomyWorker
from app.modules.vectorization import models as vectorization_models  # noqa: F401
from app.modules.vectorization.worker import VectorizationEventConsumer, VectorizationWorker
from app.platform.events.publisher import OutboxPublisher, RabbitEventPublisher
from app.platform.events.topology import build_rabbit_topology, declare_rabbit_topology
from app.platform.storage.factory import build_storage_backend
from faststream import FastStream
from faststream.rabbit import RabbitBroker

logger = get_logger(__name__)


async def run_outbox_publisher() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = build_session_factory(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
    )
    broker = RabbitBroker(settings.rabbitmq_url)
    await declare_rabbit_topology(settings)
    async with broker:
        publisher = OutboxPublisher(
            settings=settings,
            session_factory=session_factory,
            publisher=RabbitEventPublisher(broker),
        )
        await publisher.run_forever()


async def run_snapshot_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = build_session_factory(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
    )
    storage_backend = build_storage_backend(
        settings, local_root=Path(settings.content_storage_root)
    )
    topology = build_rabbit_topology(settings)
    broker = RabbitBroker(settings.rabbitmq_url)
    await declare_rabbit_topology(settings)

    @broker.subscriber(topology.snapshot_queue, exchange=topology.events_exchange)
    async def handle_content_event(message: dict[str, object]) -> None:
        envelope = EventEnvelope.model_validate(message)
        logger.info(
            "snapshot.event.received",
            event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
            event_name=envelope.event_name,
        )
        async with session_factory() as session:
            await SnapshotWorker(
                session,
                Path(settings.content_storage_root),
                storage_backend=storage_backend,
            ).handle_event(envelope)

    app = FastStream(broker)
    await app.run()


async def run_vectorization_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = build_session_factory(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
    )
    topology = build_rabbit_topology(settings)
    broker = RabbitBroker(settings.rabbitmq_url)
    await declare_rabbit_topology(settings)

    @broker.subscriber(topology.vectorization_queue, exchange=topology.events_exchange)
    async def handle_content_event(message: dict[str, object]) -> None:
        envelope = EventEnvelope.model_validate(message)
        logger.info(
            "vectorization.event.received",
            event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
            event_name=envelope.event_name,
        )
        async with session_factory() as session:
            await VectorizationEventConsumer(session).handle_event(envelope)

    async def poll_jobs() -> None:
        while True:
            async with session_factory() as session:
                processed = await VectorizationWorker(session).run_once(
                    limit=settings.vector_worker_batch_size
                )
            if processed == 0:
                await asyncio.sleep(settings.vector_worker_poll_interval_seconds)

    app = FastStream(broker)
    async with asyncio.TaskGroup() as task_group:
        task_group.create_task(poll_jobs())
        task_group.create_task(app.run())


async def run_taxonomy_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = build_session_factory(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
    )
    topology = build_rabbit_topology(settings)
    broker = RabbitBroker(settings.rabbitmq_url)
    await declare_rabbit_topology(settings)

    @broker.subscriber(topology.taxonomy_queue, exchange=topology.events_exchange)
    async def handle_content_event(message: dict[str, object]) -> None:
        envelope = EventEnvelope.model_validate(message)
        logger.info(
            "taxonomy.event.received",
            event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
            event_name=envelope.event_name,
        )
        async with session_factory() as session:
            await TaxonomyEventConsumer(session).handle_event(envelope)

    async def poll_jobs() -> None:
        while True:
            async with session_factory() as session:
                processed = await TaxonomyWorker(session).run_once(
                    limit=settings.taxonomy_worker_batch_size
                )
            if processed == 0:
                await asyncio.sleep(settings.taxonomy_worker_poll_interval_seconds)

    app = FastStream(broker)
    async with asyncio.TaskGroup() as task_group:
        task_group.create_task(poll_jobs())
        task_group.create_task(app.run())


async def run_tags_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = build_session_factory(
        settings.sqlalchemy_database_uri,
        echo=settings.sqlalchemy_echo,
    )
    topology = build_rabbit_topology(settings)
    broker = RabbitBroker(settings.rabbitmq_url)
    await declare_rabbit_topology(settings)

    @broker.subscriber(topology.tags_queue, exchange=topology.events_exchange)
    async def handle_content_event(message: dict[str, object]) -> None:
        envelope = EventEnvelope.model_validate(message)
        logger.info(
            "tags.event.received",
            event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
            event_name=envelope.event_name,
        )
        async with session_factory() as session:
            await TagsEventConsumer(session).handle_event(envelope)

    async def poll_jobs() -> None:
        while True:
            async with session_factory() as session:
                processed = await TagsWorker(session).run_once(
                    limit=settings.tags_worker_batch_size
                )
            if processed == 0:
                await asyncio.sleep(settings.tags_worker_poll_interval_seconds)

    app = FastStream(broker)
    async with asyncio.TaskGroup() as task_group:
        task_group.create_task(poll_jobs())
        task_group.create_task(app.run())


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m app.workers.main "
            "<outbox-publisher|snapshot-worker|vectorization-worker|taxonomy-worker|tags-worker>"
        )
    mode = sys.argv[1]
    if mode == "outbox-publisher":
        asyncio.run(run_outbox_publisher())
        return
    if mode == "snapshot-worker":
        asyncio.run(run_snapshot_worker())
        return
    if mode == "vectorization-worker":
        asyncio.run(run_vectorization_worker())
        return
    if mode == "taxonomy-worker":
        asyncio.run(run_taxonomy_worker())
        return
    if mode == "tags-worker":
        asyncio.run(run_tags_worker())
        return
    raise SystemExit(f"Unknown worker mode: {mode}")


if __name__ == "__main__":
    main()
