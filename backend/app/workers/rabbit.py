from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.platform.events.topology import (
    RabbitTopology,
    build_rabbit_topology,
    declare_rabbit_topology,
)
from faststream.rabbit import RabbitBroker


@dataclass(frozen=True, slots=True)
class WorkerRabbit:
    topology: RabbitTopology
    broker: RabbitBroker


def build_worker_rabbit(settings: Settings) -> WorkerRabbit:
    return WorkerRabbit(
        topology=build_rabbit_topology(settings),
        broker=RabbitBroker(settings.rabbitmq_url),
    )


async def declare_worker_rabbit_topology(settings: Settings) -> None:
    await declare_rabbit_topology(settings)
