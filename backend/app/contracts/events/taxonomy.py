from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TaxonomyClassificationCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_object_id: str
    assignment_id: str | None = None
    status: Literal["accepted", "proposed", "no_assignment"]
    assigned_by: Literal["system", "llm"] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
