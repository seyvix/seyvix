from __future__ import annotations

import asyncio

from app.platform.events.publisher import OutboxPublisher, RabbitEventPublisher
from app.workers.rabbit import build_worker_rabbit, declare_worker_rabbit_topology
from app.workers.runtime import build_worker_runtime


async def run_outbox_publisher() -> None:
    runtime = build_worker_runtime()
    worker_rabbit = build_worker_rabbit(runtime.settings)
    await declare_worker_rabbit_topology(runtime.settings)
    async with worker_rabbit.broker:
        publisher = OutboxPublisher(
            settings=runtime.settings,
            session_factory=runtime.session_factory,
            publisher=RabbitEventPublisher(worker_rabbit.broker),
        )
        await publisher.run_forever()


def main() -> None:
    asyncio.run(run_outbox_publisher())


if __name__ == "__main__":
    main()
