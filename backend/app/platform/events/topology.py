from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from app.core.config import Settings
from app.core.logging import get_logger
from faststream.rabbit import ExchangeType, QueueType, RabbitExchange, RabbitQueue

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RabbitTopology:
    events_exchange: RabbitExchange
    retry_exchange: RabbitExchange
    dlq_exchange: RabbitExchange
    snapshot_queue: RabbitQueue
    snapshot_retry_queue: RabbitQueue
    snapshot_dlq: RabbitQueue
    vectorization_queue: RabbitQueue
    vectorization_retry_queue: RabbitQueue
    vectorization_dlq: RabbitQueue
    taxonomy_queue: RabbitQueue
    taxonomy_retry_queue: RabbitQueue
    taxonomy_dlq: RabbitQueue
    tags_queue: RabbitQueue
    tags_retry_queue: RabbitQueue
    tags_dlq: RabbitQueue


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
        vectorization_queue=RabbitQueue(
            settings.rabbitmq_vectorization_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-dead-letter-exchange": retry_exchange.name,
            },
        ),
        vectorization_retry_queue=RabbitQueue(
            settings.rabbitmq_vectorization_retry_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-message-ttl": settings.rabbitmq_retry_ttl_ms,
                "x-dead-letter-exchange": events_exchange.name,
            },
        ),
        vectorization_dlq=RabbitQueue(
            settings.rabbitmq_vectorization_dlq,
            queue_type=QueueType.QUORUM,
            routing_key="#",
        ),
        taxonomy_queue=RabbitQueue(
            settings.rabbitmq_taxonomy_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-dead-letter-exchange": retry_exchange.name,
            },
        ),
        taxonomy_retry_queue=RabbitQueue(
            settings.rabbitmq_taxonomy_retry_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-message-ttl": settings.rabbitmq_retry_ttl_ms,
                "x-dead-letter-exchange": events_exchange.name,
            },
        ),
        taxonomy_dlq=RabbitQueue(
            settings.rabbitmq_taxonomy_dlq,
            queue_type=QueueType.QUORUM,
            routing_key="#",
        ),
        tags_queue=RabbitQueue(
            settings.rabbitmq_tags_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-dead-letter-exchange": retry_exchange.name,
            },
        ),
        tags_retry_queue=RabbitQueue(
            settings.rabbitmq_tags_retry_queue,
            queue_type=QueueType.QUORUM,
            routing_key="content.object.*",
            arguments={
                "x-message-ttl": settings.rabbitmq_retry_ttl_ms,
                "x-dead-letter-exchange": events_exchange.name,
            },
        ),
        tags_dlq=RabbitQueue(
            settings.rabbitmq_tags_dlq,
            queue_type=QueueType.QUORUM,
            routing_key="#",
        ),
    )


async def _connect_rabbit_with_retry(
    rabbitmq_url: str,
    *,
    max_attempts: int = 12,
    retry_delay_seconds: float = 5.0,
) -> AbstractRobustConnection:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await aio_pika.connect_robust(rabbitmq_url)
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            logger.warning(
                "rabbitmq.topology.connect.retry",
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(exc),
            )
            await asyncio.sleep(retry_delay_seconds)

    if last_error is None:
        raise RuntimeError("RabbitMQ connection retry failed without an exception.")
    raise last_error


async def declare_rabbit_topology(settings: Settings) -> None:
    topology = build_rabbit_topology(settings)
    connection = await _connect_rabbit_with_retry(settings.rabbitmq_url)
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
        vectorization_queue = await channel.declare_queue(
            topology.vectorization_queue.name,
            durable=True,
            arguments=topology.vectorization_queue.arguments,
        )
        vectorization_retry_queue = await channel.declare_queue(
            topology.vectorization_retry_queue.name,
            durable=True,
            arguments=topology.vectorization_retry_queue.arguments,
        )
        vectorization_dlq = await channel.declare_queue(
            topology.vectorization_dlq.name,
            durable=True,
            arguments=topology.vectorization_dlq.arguments,
        )
        taxonomy_queue = await channel.declare_queue(
            topology.taxonomy_queue.name,
            durable=True,
            arguments=topology.taxonomy_queue.arguments,
        )
        taxonomy_retry_queue = await channel.declare_queue(
            topology.taxonomy_retry_queue.name,
            durable=True,
            arguments=topology.taxonomy_retry_queue.arguments,
        )
        taxonomy_dlq = await channel.declare_queue(
            topology.taxonomy_dlq.name,
            durable=True,
            arguments=topology.taxonomy_dlq.arguments,
        )
        tags_queue = await channel.declare_queue(
            topology.tags_queue.name,
            durable=True,
            arguments=topology.tags_queue.arguments,
        )
        tags_retry_queue = await channel.declare_queue(
            topology.tags_retry_queue.name,
            durable=True,
            arguments=topology.tags_retry_queue.arguments,
        )
        tags_dlq = await channel.declare_queue(
            topology.tags_dlq.name,
            durable=True,
            arguments=topology.tags_dlq.arguments,
        )
        await snapshot_queue.bind(events_exchange, routing_key="content.object.*")
        await snapshot_queue.bind(events_exchange, routing_key="snapshot.requested")
        await snapshot_retry_queue.bind(retry_exchange, routing_key="content.object.*")
        await snapshot_retry_queue.bind(retry_exchange, routing_key="snapshot.requested")
        await snapshot_dlq.bind(dlq_exchange, routing_key="#")
        await vectorization_queue.bind(events_exchange, routing_key="content.object.*")
        await vectorization_retry_queue.bind(retry_exchange, routing_key="content.object.*")
        await vectorization_dlq.bind(dlq_exchange, routing_key="#")
        await taxonomy_queue.bind(events_exchange, routing_key="content.object.*")
        await taxonomy_retry_queue.bind(retry_exchange, routing_key="content.object.*")
        await taxonomy_dlq.bind(dlq_exchange, routing_key="#")
        await tags_queue.bind(events_exchange, routing_key="content.object.*")
        await tags_retry_queue.bind(retry_exchange, routing_key="content.object.*")
        await tags_dlq.bind(dlq_exchange, routing_key="#")
