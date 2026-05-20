from __future__ import annotations

import asyncio
from pathlib import Path

from app.contracts.events import EventEnvelope
from app.core.logging import get_logger
from app.modules.snapshots.worker import SnapshotWorker
from app.platform.storage.factory import build_storage_backend
from app.workers.rabbit import build_worker_rabbit, declare_worker_rabbit_topology
from app.workers.runtime import build_worker_runtime
from faststream import FastStream

logger = get_logger(__name__)


async def run_snapshot_worker() -> None:
    runtime = build_worker_runtime()
    storage_backend = build_storage_backend(
        runtime.settings,
        local_root=Path(runtime.settings.content_storage_root),
    )
    worker_rabbit = build_worker_rabbit(runtime.settings)
    await declare_worker_rabbit_topology(runtime.settings)

    @worker_rabbit.broker.subscriber(
        worker_rabbit.topology.snapshot_queue,
        exchange=worker_rabbit.topology.events_exchange,
    )
    async def handle_content_event(message: dict[str, object]) -> None:
        envelope = EventEnvelope.model_validate(message)
        logger.info(
            "snapshot.event.received",
            event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
            event_name=envelope.event_name,
        )
        async with runtime.session_factory() as session:
            await SnapshotWorker(
                session,
                Path(runtime.settings.content_storage_root),
                storage_backend=storage_backend,
            ).handle_event(envelope)

    app = FastStream(worker_rabbit.broker)
    await app.run()


def main() -> None:
    asyncio.run(run_snapshot_worker())


if __name__ == "__main__":
    main()
