from __future__ import annotations

import asyncio

from faststream import FastStream

from app.contracts.events import EventEnvelope
from app.core.logging import get_logger
from app.modules.vectorization.worker import VectorizationEventConsumer, VectorizationWorker
from app.workers.polling import poll_worker_forever
from app.workers.rabbit import build_worker_rabbit, declare_worker_rabbit_topology
from app.workers.runtime import build_worker_runtime

logger = get_logger(__name__)


async def run_vectorization_worker() -> None:
    runtime = build_worker_runtime()
    worker_rabbit = build_worker_rabbit(runtime.settings)
    await declare_worker_rabbit_topology(runtime.settings)

    @worker_rabbit.broker.subscriber(
        worker_rabbit.topology.vectorization_queue,
        exchange=worker_rabbit.topology.events_exchange,
    )
    async def handle_content_event(message: dict[str, object]) -> None:
        envelope = EventEnvelope.model_validate(message)
        logger.info(
            "vectorization.event.received",
            event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
            event_name=envelope.event_name,
        )
        async with runtime.session_factory() as session:
            await VectorizationEventConsumer(session).handle_event(envelope)

    app = FastStream(worker_rabbit.broker)
    async with asyncio.TaskGroup() as task_group:
        task_group.create_task(
            poll_worker_forever(
                runtime.session_factory,
                VectorizationWorker,
                limit=runtime.settings.vector_worker_batch_size,
                idle_sleep_seconds=runtime.settings.vector_worker_poll_interval_seconds,
            )
        )
        task_group.create_task(app.run())


def main() -> None:
    asyncio.run(run_vectorization_worker())


if __name__ == "__main__":
    main()
