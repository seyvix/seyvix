from __future__ import annotations

from app.modules.tags.event_consumer import TagsEventConsumer
from app.modules.tags.job_processor import TagsWorker

__all__ = ["TagsEventConsumer", "TagsWorker"]
