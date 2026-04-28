from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventName = Literal[
    "content.object.created",
    "content.object.updated",
    "snapshot.requested",
    "snapshot.completed",
    "snapshot.failed",
]


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_name: EventName
    event_version: int = 1
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str
    user_id: str | None = None
    entity_id: str
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def reject_large_inline_data(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_large_inline_data(value)
        return value

    @classmethod
    def new(
        cls,
        *,
        event_name: EventName,
        entity_id: str,
        correlation_id: str,
        user_id: str | None,
        payload: BaseModel | dict[str, Any],
        event_version: int = 1,
    ) -> EventEnvelope:
        payload_value = (
            payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        )
        return cls(
            event_name=event_name,
            event_version=event_version,
            correlation_id=correlation_id,
            user_id=user_id,
            entity_id=entity_id,
            payload=payload_value,
        )


LARGE_DATA_KEYS = {
    "binary",
    "body",
    "content",
    "data",
    "embedding",
    "embeddings",
    "file",
    "html",
    "markdown",
    "text",
    "vector",
    "vectors",
}


def _reject_large_inline_data(value: object, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).casefold()
            if normalized_key in LARGE_DATA_KEYS:
                raise ValueError(f"large data must not be embedded in event {path}.{key}")
            _reject_large_inline_data(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_large_inline_data(child, path=f"{path}[{index}]")
