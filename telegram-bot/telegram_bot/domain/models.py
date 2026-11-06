from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from telegram_bot.domain.enums import BotMode


class MaterialType(StrEnum):
    """Wire values understood by the backend. Voice notes are sent as `audio` and round video
    notes as `video`: the backend treats them like any other audio/video file."""

    TEXT = "text"
    LINK = "link"
    PHOTO = "photo"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class Attachment:
    file_id: str
    filename: str
    mime_type: str | None
    file_size: int | None = None


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    provider: str
    provider_label: str
    external_id: str
    url: str | None = None
    title: str | None = None
    original_created_at: str | None = None
    origin: dict[str, Any] | None = None
    author: dict[str, Any] | None = None
    group_id: str | None = None
    entities: list[dict[str, Any]] | None = None
    custom_emoji_ids: list[str] | None = None
    raw_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    def with_metadata(self, metadata: dict[str, Any]) -> SourceMetadata:
        return replace(self, metadata=metadata)


@dataclass(frozen=True, slots=True)
class InboundMaterial:
    telegram_user_id: str
    telegram_chat_id: str
    telegram_message_id: str
    message_date: int
    material_type: MaterialType
    text: str | None
    caption: str | None
    attachment: Attachment | None
    source: SourceMetadata | None = None


@dataclass(frozen=True, slots=True)
class SavedMaterial:
    title: str
    id: str | None = None
    status: str = "saved"


@dataclass(frozen=True, slots=True)
class UserContext:
    telegram_user_id: int
    allowed: bool
    is_admin: bool
    linked: bool
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class BotState:
    telegram_user_id: int
    mode: BotMode
    active_collection_id: str | None = None
    manual_collection_started_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AccessGrant:
    id: str
    telegram_user_id: int | None
    username: str | None
    note: str | None
    display_name: str | None
    last_login_at: str | None


@dataclass(frozen=True, slots=True)
class AccessList:
    mode: str
    admins: list[int]
    items: list[AccessGrant]
