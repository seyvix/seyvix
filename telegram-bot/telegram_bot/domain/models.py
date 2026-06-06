from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from telegram_bot.domain.enums import BotMode


class MaterialType(StrEnum):
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
    id: str | None = None
    status: str = "saved"


@dataclass(frozen=True, slots=True)
class UserContext:
    telegram_user_id: str
    linked: bool
    user_id: str | None = None
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class BotState:
    telegram_user_id: str
    mode: BotMode
    created_at: datetime
    updated_at: datetime
    active_collection_id: str | None = None
    auto_group_collection_id: str | None = None
    auto_group_last_message_at: datetime | None = None
    manual_collection_started_at: datetime | None = None
    manual_collection_last_item_at: datetime | None = None
    manual_collection_reminder_sent_at: datetime | None = None

    def with_mode(self, mode: BotMode, *, now: datetime) -> BotState:
        if mode != BotMode.MANUAL_COLLECTION:
            return replace(
                self,
                mode=mode,
                active_collection_id=None,
                manual_collection_started_at=None,
                manual_collection_last_item_at=None,
                manual_collection_reminder_sent_at=None,
                updated_at=now,
            )
        return replace(self, mode=mode, updated_at=now)

    def with_manual_collection(self, *, collection_id: str, now: datetime) -> BotState:
        return replace(
            self,
            mode=BotMode.MANUAL_COLLECTION,
            active_collection_id=collection_id,
            manual_collection_started_at=self.manual_collection_started_at or now,
            manual_collection_last_item_at=now,
            manual_collection_reminder_sent_at=None,
            updated_at=now,
        )

    def with_auto_group(self, *, collection_id: str | None, now: datetime) -> BotState:
        return replace(
            self,
            auto_group_collection_id=collection_id,
            auto_group_last_message_at=now if collection_id is not None else None,
            updated_at=now,
        )

    def finish_collection(self, *, now: datetime) -> BotState:
        return replace(
            self,
            mode=BotMode.AUTO,
            active_collection_id=None,
            manual_collection_started_at=None,
            manual_collection_last_item_at=None,
            manual_collection_reminder_sent_at=None,
            updated_at=now,
        )

    def mark_manual_collection_reminder_sent(self, *, now: datetime) -> BotState:
        return replace(self, manual_collection_reminder_sent_at=now, updated_at=now)
