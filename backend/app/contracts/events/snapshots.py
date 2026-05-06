from __future__ import annotations

from typing import Any

from app.contracts.events.base import _reject_large_inline_data
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SnapshotRequestedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_object_id: str
    source_asset_id: str | None = None
    job_types: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def reject_large_inline_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_large_inline_data(value, path="metadata")
        return value
