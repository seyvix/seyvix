from __future__ import annotations

from aiogram.types import Message

from telegram_bot.domain.models import MaterialType
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

    assert material is not None
    assert material.telegram_user_id == "100500"
    assert material.telegram_chat_id == "700"
    assert material.telegram_message_id == "15"
    assert material.message_date == 1_777_777_777
    assert material.material_type == MaterialType.TEXT
    assert material.text == "Markdown **note**"
    assert material.caption is None
    assert material.attachment is None
    assert material.source is not None
    assert material.source.provider == "telegram"


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


def test_parse_message_maps_video_attachment() -> None:
    material = material_from_mapping(
        {
            "message_id": 19,
            "date": 1_777_777_781,
            "chat": {"id": 700},
            "from": {"id": 100500},
            "caption": "Video caption",
            "video": {
                "file_id": "video-file",
                "file_name": "clip.mp4",
                "mime_type": "video/mp4",
                "duration": 12,
            },
        }
    )

    assert material is not None
    assert material.material_type == MaterialType.VIDEO
    assert material.caption == "Video caption"
    assert material.attachment is not None
    assert material.attachment.file_id == "video-file"
    assert material.attachment.filename == "clip.mp4"
    assert material.attachment.mime_type == "video/mp4"


def test_parse_message_maps_video_note_as_video() -> None:
    material = material_from_mapping(
        {
            "message_id": 20,
            "date": 1_777_777_782,
            "chat": {"id": 700},
            "from": {"id": 100500},
            "video_note": {
                "file_id": "round-video-file",
                "duration": 5,
                "length": 240,
            },
        }
    )

    assert material is not None
    assert material.material_type == MaterialType.VIDEO
    assert material.attachment is not None
    assert material.attachment.file_id == "round-video-file"
    assert material.attachment.filename == "telegram-video-note.mp4"
    assert material.attachment.mime_type == "video/mp4"
    assert material.source is not None
    assert material.source.raw_payload["video_note"]["file_id"] == "round-video-file"


def test_parse_message_maps_voice_as_audio() -> None:
    material = material_from_mapping(
        {
            "message_id": 21,
            "date": 1_777_777_783,
            "chat": {"id": 700},
            "from": {"id": 100500},
            "voice": {
                "file_id": "voice-file",
                "mime_type": "audio/ogg",
                "duration": 7,
            },
        }
    )

    assert material is not None
    assert material.material_type == MaterialType.AUDIO
    assert material.attachment is not None
    assert material.attachment.file_id == "voice-file"
    assert material.attachment.filename == "telegram-voice.ogg"
    assert material.attachment.mime_type == "audio/ogg"
    assert material.source is not None
    assert material.source.raw_payload["voice"]["file_id"] == "voice-file"


def test_parse_message_preserves_telegram_source_metadata_and_markdown() -> None:
    material = material_from_mapping(
        {
            "message_id": 29,
            "date": 1_778_425_087,
            "chat": {"id": 801627037, "type": "private"},
            "from": {"id": 801627037, "is_bot": False, "first_name": "lv"},
            "forward_origin": {
                "type": "channel",
                "chat": {
                    "id": -1001319248631,
                    "title": "Бэкдор",
                    "username": "whackdoor",
                    "type": "channel",
                },
                "message_id": 28305,
                "date": 1_778_411_961,
            },
            "media_group_id": "14227400699706618",
            "photo": [
                {"file_id": "small", "file_unique_id": "small-u", "file_size": 10},
                {"file_id": "large", "file_unique_id": "large-u", "file_size": 50},
            ],
            "caption": "⚡️ Важно\n\nБэкдор",
            "caption_entities": [
                {"offset": 0, "length": 8, "type": "bold"},
                {
                    "offset": 10,
                    "length": 6,
                    "type": "text_link",
                    "url": "https://t.me/whackdoor",
                },
                {
                    "offset": 0,
                    "length": 2,
                    "type": "custom_emoji",
                    "custom_emoji_id": "5280586677532774817",
                },
            ],
        }
    )

    assert material is not None
    assert (
        material.caption
        == "**{{tg_emoji:5280586677532774817|⚡️}} Важно**\n\n[Бэкдор](https://t.me/whackdoor)"
    )
    assert material.source is not None
    assert material.source.provider == "telegram"
    assert material.source.external_id == "801627037:29"
    assert material.source.group_id == "14227400699706618"
    assert material.source.origin is not None
    assert material.source.origin["title"] == "Бэкдор"
    assert material.source.origin["username"] == "whackdoor"
    assert material.source.origin["url"] == "https://t.me/whackdoor/28305"
    assert material.source.entities[0]["type"] == "bold"
    assert material.source.custom_emoji_ids == ["5280586677532774817"]
    assert material.source.raw_payload["message_id"] == 29


def test_parse_private_forward_without_from_user_uses_private_chat_as_sender() -> None:
    material = material_from_mapping(
        {
            "message_id": 33,
            "date": 1_778_425_100,
            "chat": {
                "id": 801627037,
                "first_name": "lv",
                "username": "hardzz",
                "type": "private",
            },
            "forward_from_chat": {
                "id": -1001319248631,
                "title": "Бэкдор",
                "username": "whackdoor",
                "type": "channel",
            },
            "forward_from_message_id": 28305,
            "forward_date": 1_778_411_961,
            "text": "legacy forwarded text",
        }
    )

    assert material is not None
    assert material.telegram_user_id == "801627037"
    assert material.telegram_chat_id == "801627037"
    assert material.text == "legacy forwarded text"
    assert material.source is not None
    assert material.source.origin is not None
    assert material.source.origin["title"] == "Бэкдор"
    assert material.source.origin["url"] == "https://t.me/whackdoor/28305"


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
