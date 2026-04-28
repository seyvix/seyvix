from __future__ import annotations

from dataclasses import dataclass

import aio_pika
from faststream.rabbit import ExchangeType, QueueType, RabbitExchange, RabbitQueue

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class RabbitTopology:
    events_exchange: RabbitExchange
    retry_exchange: RabbitExchange
    dlq_exchange: RabbitExchange
    snapshot_queue: RabbitQueue
    snapshot_retry_queue: RabbitQueue
    snapshot_dlq: RabbitQueue


def build_rabbit_topology(settings: Settings) -> RabbitTopology:
    events_exchange = RabbitExchange(
        settings.rabbitmq_exchange,
        type=ExchangeType.TOPIC,
        durable=True,
    )
    retry_exchange = RabbitExchange(
        f"{settings.rabbitmq_exchange}.retry",
        type=ExchangeType.TOPIC,
        durable=True,
    )
    dlq_exchange = RabbitExchange(
        f"{settings.rabbitmq_exchange}.dlq",
        type=ExchangeType.TOPIC,
        durable=True,
    )
    return RabbitTopology(
        events_exchange=events_exchange,
        retry_exchange=retry_exchange,
        dlq_exchange=dlq_exchange,
        snapshot_queue=RabbitQueue(
            settings.rabbitmq_snapshot_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-dead-letter-exchange": retry_exchange.name,
                "x-dead-letter-routing-key": "content.object.created",
            },
        ),
        snapshot_retry_queue=RabbitQueue(
            settings.rabbitmq_snapshot_retry_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-message-ttl": settings.rabbitmq_retry_ttl_ms,
                "x-dead-letter-exchange": events_exchange.name,
            },
        ),
        snapshot_dlq=RabbitQueue(
            settings.rabbitmq_snapshot_dlq,
            queue_type=QueueType.QUORUM,
            routing_key="#",
        ),
    )


async def declare_rabbit_topology(settings: Settings) -> None:
    topology = build_rabbit_topology(settings)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        events_exchange = await channel.declare_exchange(
            topology.events_exchange.name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        retry_exchange = await channel.declare_exchange(
            topology.retry_exchange.name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        dlq_exchange = await channel.declare_exchange(
            topology.dlq_exchange.name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        snapshot_queue = await channel.declare_queue(
            topology.snapshot_queue.name,
            durable=True,
            arguments=topology.snapshot_queue.arguments,
        )
        snapshot_retry_queue = await channel.declare_queue(
            topology.snapshot_retry_queue.name,
            durable=True,
            arguments=topology.snapshot_retry_queue.arguments,
        )
        snapshot_dlq = await channel.declare_queue(
            topology.snapshot_dlq.name,
            durable=True,
            arguments=topology.snapshot_dlq.arguments,
        )
        await snapshot_queue.bind(events_exchange, routing_key="content.object.*")
        await snapshot_queue.bind(events_exchange, routing_key="snapshot.requested")
        await snapshot_retry_queue.bind(retry_exchange, routing_key="content.object.*")
        await snapshot_retry_queue.bind(retry_exchange, routing_key="snapshot.requested")
        await snapshot_dlq.bind(dlq_exchange, routing_key="#")
