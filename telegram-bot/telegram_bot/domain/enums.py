from __future__ import annotations

from enum import StrEnum


class BotMode(StrEnum):
    AUTO = "auto"
    SEPARATE = "separate"
    MANUAL_COLLECTION = "manual_collection"
