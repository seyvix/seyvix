from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ContentClassificationInput(BaseModel):
    content_object_id: str
    title: str
    text_excerpt: str | None
    url: str | None
    tags: list[str]
    metadata: dict[str, str | int | bool | None]
    created_at: datetime
    updated_at: datetime
