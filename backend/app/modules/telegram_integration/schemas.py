from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.auth.security import normalize_telegram_username
from app.modules.content.app_note import AppNote

BotMode = Literal["auto", "separate", "manual_collection"]
TelegramMaterialType = Literal[
    "text",
    "link",
    "photo",
    "document",
    "audio",
    "voice",
    "video",
    "video_note",
]
TelegramIngestStatus = Literal["saved", "collection_started", "collection_updated"]

MAX_INGEST_GROUPS = 20
MAX_INGEST_PARTS = 50
MAX_INGEST_FILES = 20


class TelegramUserStatusResponse(BaseModel):
    telegram_user_id: int
    allowed: bool = Field(description="May use Seyvix (admin, allowlisted or open mode).")
    is_admin: bool
    linked: bool = Field(description="A Seyvix account exists (signed in on the web once).")
    user_id: str | None = None
    display_name: str | None = None


class BotStateResponse(BaseModel):
    telegram_user_id: int
    mode: BotMode
    active_collection_id: str | None
    manual_collection_started_at: datetime | None


class BotModeRequest(BaseModel):
    mode: BotMode


class FinishCollectionResponse(BaseModel):
    finished: bool = Field(description="False when there was no active collection.")
    state: BotStateResponse


class ReminderClaimRequest(BaseModel):
    idle_seconds: int = Field(ge=60, le=7 * 86400)


class ReminderClaimResponse(BaseModel):
    telegram_user_ids: list[int]


class InternalAccessGrantRequest(BaseModel):
    actor_telegram_id: int = Field(gt=0)
    telegram_user_id: int | None = Field(default=None, gt=0)
    username: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return normalize_telegram_username(value)

    @model_validator(mode="after")
    def require_identity(self) -> InternalAccessGrantRequest:
        if self.telegram_user_id is None and self.username is None:
            raise ValueError("Either telegram_user_id or username is required.")
        return self


class InternalAccessRevokeRequest(BaseModel):
    actor_telegram_id: int = Field(gt=0)
    telegram_user_id: int | None = Field(default=None, gt=0)
    username: str | None = Field(default=None, max_length=64)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return normalize_telegram_username(value)

    @model_validator(mode="after")
    def require_identity(self) -> InternalAccessRevokeRequest:
        if self.telegram_user_id is None and self.username is None:
            raise ValueError("Either telegram_user_id or username is required.")
        return self


class InternalAccessRevokeResponse(BaseModel):
    sessions_revoked: int


class UniversalSourcePayload(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    provider_label: str | None = Field(default=None, max_length=128)
    external_id: str = Field(min_length=1, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    original_created_at: datetime | None = None
    origin: dict[str, Any] | None = None
    author: dict[str, Any] | None = None
    group_id: str | None = Field(default=None, max_length=512)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    custom_emoji_ids: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TelegramIngestPart(BaseModel):
    """One Telegram message (text and/or one attachment)."""

    telegram_message_id: str = Field(min_length=1, max_length=64)
    material_type: TelegramMaterialType
    message_date: datetime | None = None
    text: str | None = Field(default=None, max_length=100_000)
    caption: str | None = Field(default=None, max_length=100_000)
    filename: str | None = Field(default=None, max_length=512)
    mime_type: str | None = Field(default=None, max_length=255)
    file_index: int | None = Field(default=None, ge=0, description="Index into `files`.")
    source: UniversalSourcePayload | None = None


class TelegramIngestGroup(BaseModel):
    """Parts that form one logical Telegram message (e.g. an album) → one note."""

    parts: list[TelegramIngestPart] = Field(min_length=1, max_length=MAX_INGEST_PARTS)


class TelegramIngestRequest(BaseModel):
    telegram_user_id: int = Field(gt=0)
    telegram_chat_id: str = Field(min_length=1, max_length=64)
    groups: list[TelegramIngestGroup] = Field(min_length=1, max_length=MAX_INGEST_GROUPS)

    @model_validator(mode="after")
    def limit_parts(self) -> TelegramIngestRequest:
        if sum(len(group.parts) for group in self.groups) > MAX_INGEST_PARTS:
            raise ValueError(f"At most {MAX_INGEST_PARTS} parts per request.")
        return self

    def file_indexes(self) -> list[int]:
        return [
            part.file_index
            for group in self.groups
            for part in group.parts
            if part.file_index is not None
        ]


class TelegramIngestResponse(BaseModel):
    status: TelegramIngestStatus
    note: AppNote
