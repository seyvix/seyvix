from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="content",
    description="Canonical content records, metadata, and ingestion lifecycle management.",
    public_contracts=[
        "content-record",
        "content-version",
        "ingestion-job",
        "content-classification-input",
    ],
    plugin_capabilities=["content_ingestor", "content_post_processor"],
)


class ContentClassificationInput(BaseModel):
    content_object_id: str
    title: str
    text_excerpt: str | None
    url: str | None
    tags: list[str]
    metadata: dict[str, str | int | bool | None]
    created_at: datetime
    updated_at: datetime
