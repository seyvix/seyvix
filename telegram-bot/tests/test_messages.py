from __future__ import annotations

from aiogram.types import Message

from telegram_bot.domain.models import InboundMaterial, MaterialType
from telegram_bot.presentation.telegram.message_mapper import (
    material_from_mapping,
    material_from_message,
)


def test_material_from_aiogram_message_uses_telegram_from_alias() -> None:
    message = Message.model_validate(
        {
            "message_id": 18,
            "date": 1_777_777_780,
            "chat": {"id": 700, "type": "private"},
            "from": {"id": 100500, "is_bot": False, "first_name": "User"},
            "text": "Plain note from aiogram",
        }
    )

    material = material_from_message(message)

    assert material is not None
    assert material.telegram_user_id == "100500"
    assert material.telegram_chat_id == "700"
    assert material.material_type == MaterialType.TEXT
    assert material.text == "Plain note from aiogram"


def test_parse_message_extracts_plain_text_payload() -> None:
    material = material_from_mapping(
        {
            "message_id": 15,
            "date": 1_777_777_777,
            "chat": {"id": 700},
            "from": {"id": 100500},
            "text": "Markdown **note**",
        }
    )

    assert material == InboundMaterial(
        telegram_user_id="100500",
        telegram_chat_id="700",
        telegram_message_id="15",
        message_date=1_777_777_777,
        material_type=MaterialType.TEXT,
        text="Markdown **note**",
        caption=None,
        attachment=None,
    )


def test_parse_message_uses_largest_photo_and_caption() -> None:
    material = material_from_mapping(
        {
            "message_id": 16,
            "date": 1_777_777_778,
            "chat": {"id": 700},
            "from": {"id": 100500},
            "caption": "Image caption",
            "photo": [
                {"file_id": "small", "file_size": 10},
                {"file_id": "large", "file_size": 50},
            ],
        }
    )

    assert material is not None
    assert material.material_type == MaterialType.PHOTO
    assert material.caption == "Image caption"
    assert material.attachment is not None
    assert material.attachment.file_id == "large"
    assert material.attachment.filename == "telegram-photo.jpg"
    assert material.attachment.mime_type == "image/jpeg"


def test_parse_message_ignores_bot_commands() -> None:
    assert (
        material_from_mapping(
            {
                "message_id": 17,
                "date": 1_777_777_779,
                "chat": {"id": 700},
                "from": {"id": 100500},
                "text": "/start",
            }
        )
        is None
    )
