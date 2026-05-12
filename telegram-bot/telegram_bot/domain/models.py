from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any


class MaterialType(StrEnum):
    TEXT = "text"
    LINK = "link"
    PHOTO = "photo"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


class IngestMode(StrEnum):
    DEFAULT = "default"
    GROUPED_NOTES = "grouped_notes"


@dataclass(frozen=True, slots=True)
class Attachment:
    file_id: str
    filename: str
    mime_type: str | None
    data: bytes | None = None

    def with_data(self, data: bytes) -> Attachment:
        return replace(self, data=data)


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

    def with_attachment_data(self, data: bytes) -> InboundMaterial:
        if self.attachment is None:
            return self
        return replace(self, attachment=self.attachment.with_data(data))


@dataclass(frozen=True, slots=True)
class SavedMaterial:
    title: str
