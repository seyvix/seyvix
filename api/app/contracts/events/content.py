from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContentObjectChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_object_id: str
    asset_ids: list[str] = Field(default_factory=list)
    storage_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("storage_refs")
    @classmethod
    def storage_refs_must_be_references(cls, value: list[str]) -> list[str]:
        invalid = [item for item in value if not item.startswith(("s3://", "local://"))]
        if invalid:
            raise ValueError("storage_refs must contain object storage references")
        return value
