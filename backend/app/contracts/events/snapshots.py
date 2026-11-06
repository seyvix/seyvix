from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.events.base import _reject_large_inline_data


class SnapshotTextRepresentationCompletedPayload(BaseModel):
    """Every text-extraction (markdown) job of a content object reached a terminal state.

    `artifact_id`/`source_asset_id` point at the markdown artifact that triggered the event;
    both are None when the last job failed permanently (consumers still index title/text).
    """

    model_config = ConfigDict(extra="forbid")

    content_object_id: str
    source_asset_id: str | None = None
    artifact_id: str | None = None
    representation_type: str = "markdown"
    source_media_type: str | None = None
    source_mime_type: str | None = None
    source_filename: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def reject_large_inline_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_large_inline_data(value, path="metadata")
        return value
