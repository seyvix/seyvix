from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class MaterialType(StrEnum):
    TEXT = "text"
    LINK = "link"
    PHOTO = "photo"
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
class InboundMaterial:
    telegram_user_id: str
    telegram_chat_id: str
    telegram_message_id: str
    message_date: int
    material_type: MaterialType
    text: str | None
    caption: str | None
    attachment: Attachment | None

    def with_attachment_data(self, data: bytes) -> InboundMaterial:
        if self.attachment is None:
            return self
        return replace(self, attachment=self.attachment.with_data(data))


@dataclass(frozen=True, slots=True)
class SavedMaterial:
    title: str
