"""Static event routing: which consumer queues receive which events.

A consumer name is a queue name in `event_deliveries.consumer`. Any process, in any
language, may serve a consumer queue by following the SQL protocol in docs/ARCHITECTURE.md.
Events without routes are still recorded in `events` (useful for audit/debugging).
"""

from __future__ import annotations

from typing import Final, cast

from app.contracts.events.base import EventName

CONSUMER_SNAPSHOTS: Final = "snapshots"
CONSUMER_VECTORIZATION: Final = "vectorization"
CONSUMER_TAGS: Final = "tags"
CONSUMER_TAXONOMY: Final = "taxonomy"

EVENT_ROUTES: Final[dict[EventName, tuple[str, ...]]] = {
    "content.object.created": (CONSUMER_SNAPSHOTS,),
    "content.object.updated": (CONSUMER_SNAPSHOTS,),
    "content.object.deleted": (CONSUMER_VECTORIZATION,),
    "snapshot.text_representation.completed": (CONSUMER_VECTORIZATION, CONSUMER_TAGS),
    "content.tags.completed": (CONSUMER_TAXONOMY,),
}


def consumers_for(event_name: str) -> tuple[str, ...]:
    return EVENT_ROUTES.get(cast(EventName, event_name), ())
