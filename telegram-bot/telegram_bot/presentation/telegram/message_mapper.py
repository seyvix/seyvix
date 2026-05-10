from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from aiogram.types import Message

from telegram_bot.domain.models import Attachment, InboundMaterial, MaterialType


def material_from_message(message: Message) -> InboundMaterial | None:
    if message.from_user is None:
        return None

    payload = message.model_dump(mode="python", by_alias=True)
    return material_from_mapping(payload)


def material_from_mapping(message: Mapping[str, Any]) -> InboundMaterial | None:
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(sender, Mapping) or not isinstance(chat, Mapping):
        return None

    text = message.get("text")
    if isinstance(text, str) and text.startswith("/"):
        return None

    telegram_user_id = str(sender.get("id", ""))
    telegram_chat_id = str(chat.get("id", ""))
    telegram_message_id = str(message.get("message_id", ""))
    message_date = _message_date_as_timestamp(message.get("date"))
    caption = message.get("caption") if isinstance(message.get("caption"), str) else None

    document = message.get("document")
    if isinstance(document, Mapping) and document.get("file_id"):
        return InboundMaterial(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=MaterialType.DOCUMENT,
            text=None,
            caption=caption,
            attachment=Attachment(
                file_id=str(document["file_id"]),
                filename=str(document.get("file_name") or "telegram-document"),
                mime_type=(
                    str(document["mime_type"]) if document.get("mime_type") is not None else None
                ),
            ),
        )

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        photo = max(
            (item for item in photos if isinstance(item, Mapping) and item.get("file_id")),
            key=lambda item: int(item.get("file_size") or 0),
            default=None,
        )
        if photo is not None:
            return InboundMaterial(
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=telegram_message_id,
                message_date=message_date,
                material_type=MaterialType.PHOTO,
                text=None,
                caption=caption,
                attachment=Attachment(
                    file_id=str(photo["file_id"]),
                    filename="telegram-photo.jpg",
                    mime_type="image/jpeg",
                ),
            )

    if isinstance(text, str) and text.strip():
        material_type = MaterialType.LINK if _is_plain_http_url(text.strip()) else MaterialType.TEXT
        return InboundMaterial(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=material_type,
            text=text,
            caption=None,
            attachment=None,
        )

    return None


def _message_date_as_timestamp(value: object) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _is_plain_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://")) and not any(char.isspace() for char in value)
