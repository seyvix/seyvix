from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.modules.content.app_note import AppNote
from pydantic import BaseModel, Field

TelegramIngestMode = Literal["default", "grouped_notes"]
TelegramMaterialType = Literal["text", "link", "photo", "document"]
TelegramIngestStatus = Literal["saved", "collection_started", "collection_updated"]


class TelegramModeRequest(BaseModel):
    telegram_user_id: str = Field(min_length=1, max_length=64)
    mode: TelegramIngestMode


class TelegramModeResponse(BaseModel):
    mode: TelegramIngestMode


class TelegramFinishRequest(BaseModel):
    telegram_user_id: str = Field(min_length=1, max_length=64)


class TelegramFinishResponse(BaseModel):
    status: Literal["finished"]


class TelegramIngestPayload(BaseModel):
    telegram_user_id: str = Field(min_length=1, max_length=64)
    telegram_chat_id: str = Field(min_length=1, max_length=64)
    telegram_message_id: str = Field(min_length=1, max_length=64)
    material_type: TelegramMaterialType
    message_date: datetime | None = None
    text: str | None = None
    caption: str | None = None
    filename: str | None = Field(default=None, max_length=512)
    mime_type: str | None = Field(default=None, max_length=255)


class TelegramIngestResponse(BaseModel):
    status: TelegramIngestStatus
    mode: TelegramIngestMode
    note: AppNote
