from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from aiogram.types import Message
from telegram_bot.domain.models import Attachment, InboundMaterial, MaterialType, SourceMetadata


def material_from_message(message: Message) -> InboundMaterial | None:
    payload = message.model_dump(mode="python", by_alias=True)
    return material_from_mapping(payload)


def material_from_mapping(message: Mapping[str, Any]) -> InboundMaterial | None:
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(chat, Mapping):
        return None
    if not isinstance(sender, Mapping):
        sender = chat if chat.get("type") == "private" else None
    if not isinstance(sender, Mapping):
        return None

    text = message.get("text")
    if isinstance(text, str) and text.startswith("/"):
        return None

    telegram_user_id = str(sender.get("id", ""))
    telegram_chat_id = str(chat.get("id", ""))
    telegram_message_id = str(message.get("message_id", ""))
    message_date = _message_date_as_timestamp(message.get("date"))
    caption = _markdown_text(
        message.get("caption"),
        message.get("caption_entities"),
    )
    source = _source_metadata(
        message=message,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
    )

    document = message.get("document")
    if isinstance(document, Mapping) and document.get("file_id"):
        return _attachment_material(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=MaterialType.DOCUMENT,
            caption=caption,
            source=source,
            file_id=str(document["file_id"]),
            filename=str(document.get("file_name") or "telegram-document"),
            mime_type=_string_or_none(document.get("mime_type")),
        )

    video = message.get("video")
    if isinstance(video, Mapping) and video.get("file_id"):
        return _attachment_material(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=MaterialType.VIDEO,
            caption=caption,
            source=source,
            file_id=str(video["file_id"]),
            filename=str(video.get("file_name") or "telegram-video.mp4"),
            mime_type=_string_or_none(video.get("mime_type")) or "video/mp4",
        )

    video_note = message.get("video_note")
    if isinstance(video_note, Mapping) and video_note.get("file_id"):
        return _attachment_material(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=MaterialType.VIDEO,
            caption=caption,
            source=source,
            file_id=str(video_note["file_id"]),
            filename="telegram-video-note.mp4",
            mime_type="video/mp4",
        )

    voice = message.get("voice")
    if isinstance(voice, Mapping) and voice.get("file_id"):
        return _attachment_material(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=MaterialType.AUDIO,
            caption=caption,
            source=source,
            file_id=str(voice["file_id"]),
            filename="telegram-voice.ogg",
            mime_type=_string_or_none(voice.get("mime_type")) or "audio/ogg",
        )

    audio = message.get("audio")
    if isinstance(audio, Mapping) and audio.get("file_id"):
        return _attachment_material(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=MaterialType.AUDIO,
            caption=caption,
            source=source,
            file_id=str(audio["file_id"]),
            filename=str(audio.get("file_name") or "telegram-audio.mp3"),
            mime_type=_string_or_none(audio.get("mime_type")) or "audio/mpeg",
        )

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        photo = max(
            (item for item in photos if isinstance(item, Mapping) and item.get("file_id")),
            key=lambda item: int(item.get("file_size") or 0),
            default=None,
        )
        if photo is not None:
            return _attachment_material(
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=telegram_message_id,
                message_date=message_date,
                material_type=MaterialType.PHOTO,
                caption=caption,
                source=source,
                file_id=str(photo["file_id"]),
                filename="telegram-photo.jpg",
                mime_type="image/jpeg",
            )

    if isinstance(text, str) and text.strip():
        markdown_text = _markdown_text(text, message.get("entities")) or text
        material_type = (
            MaterialType.LINK if _is_plain_http_url(markdown_text.strip()) else MaterialType.TEXT
        )
        return InboundMaterial(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            message_date=message_date,
            material_type=material_type,
            text=markdown_text,
            caption=None,
            attachment=None,
            source=source,
        )

    return None


def _attachment_material(
    *,
    telegram_user_id: str,
    telegram_chat_id: str,
    telegram_message_id: str,
    message_date: int,
    material_type: MaterialType,
    caption: str | None,
    source: SourceMetadata,
    file_id: str,
    filename: str,
    mime_type: str | None,
) -> InboundMaterial:
    return InboundMaterial(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        message_date=message_date,
        material_type=material_type,
        text=None,
        caption=caption,
        attachment=Attachment(
            file_id=file_id,
            filename=filename,
            mime_type=mime_type,
        ),
        source=source,
    )


def _string_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


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


def _markdown_text(value: object, entities_value: object) -> str | None:
    if not isinstance(value, str):
        return None
    entities = [item for item in entities_value or [] if isinstance(item, Mapping)]
    if not entities:
        return value
    replacements: list[tuple[int, int, str, str, str]] = []
    entity_ranges = [
        _entity_range(value, entity) for entity in entities if isinstance(entity.get("type"), str)
    ]
    non_custom_ranges = [
        item for item in entity_ranges if item is not None and item[2].get("type") != "custom_emoji"
    ]
    custom_ranges = [
        item for item in entity_ranges if item is not None and item[2].get("type") == "custom_emoji"
    ]

    for start, end, entity in entity_ranges:
        entity_type = entity.get("type")
        if entity_type == "custom_emoji" and _is_covered_by_non_custom(
            start=start,
            end=end,
            ranges=non_custom_ranges,
        ):
            continue
        segment = _render_segment_with_custom_emoji(value, start, end, custom_ranges)
        prefix = suffix = ""
        replacement = segment
        if entity_type == "custom_emoji" and entity.get("custom_emoji_id"):
            replacement = _telegram_emoji_marker(str(entity["custom_emoji_id"]), value[start:end])
        elif entity_type == "bold":
            prefix, suffix = "**", "**"
        elif entity_type == "italic":
            prefix, suffix = "_", "_"
        elif entity_type == "underline":
            prefix, suffix = "<u>", "</u>"
        elif entity_type == "strikethrough":
            prefix, suffix = "~~", "~~"
        elif entity_type == "code":
            prefix, suffix = "`", "`"
        elif entity_type == "pre":
            prefix, suffix = "```\n", "\n```"
        elif entity_type == "spoiler":
            prefix, suffix = "||", "||"
        elif entity_type == "text_link" and entity.get("url"):
            replacement = f"[{segment}]({entity['url']})"
        elif entity_type == "blockquote":
            replacement = "\n".join(f"> {line}" if line else ">" for line in segment.splitlines())
        else:
            continue
        replacements.append((start, end, prefix, suffix, replacement))

    result = value
    for start, end, prefix, suffix, replacement in sorted(
        replacements,
        key=lambda item: (item[0], item[1]),
        reverse=True,
    ):
        if prefix or suffix:
            replacement = f"{prefix}{replacement}{suffix}"
        result = f"{result[:start]}{replacement}{result[end:]}"
    return result


def _entity_range(
    value: str,
    entity: Mapping[str, Any],
) -> tuple[int, int, Mapping[str, Any]] | None:
    offset = entity.get("offset")
    length = entity.get("length")
    if not isinstance(offset, int) or not isinstance(length, int) or length <= 0:
        return None
    start = _utf16_index_to_py_index(value, offset)
    end = _utf16_index_to_py_index(value, offset + length)
    if start is None or end is None or start >= end:
        return None
    return start, end, entity


def _is_covered_by_non_custom(
    *,
    start: int,
    end: int,
    ranges: list[tuple[int, int, Mapping[str, Any]]],
) -> bool:
    return any(other_start <= start and end <= other_end for other_start, other_end, _ in ranges)


def _render_segment_with_custom_emoji(
    value: str,
    start: int,
    end: int,
    custom_ranges: list[tuple[int, int, Mapping[str, Any]]],
) -> str:
    result = value[start:end]
    for custom_start, custom_end, entity in sorted(
        (
            item
            for item in custom_ranges
            if start <= item[0] and item[1] <= end and item[2].get("custom_emoji_id")
        ),
        key=lambda item: item[0],
        reverse=True,
    ):
        local_start = custom_start - start
        local_end = custom_end - start
        fallback = result[local_start:local_end]
        marker = _telegram_emoji_marker(str(entity["custom_emoji_id"]), fallback)
        result = f"{result[:local_start]}{marker}{result[local_end:]}"
    return result


def _telegram_emoji_marker(custom_emoji_id: str, fallback: str) -> str:
    safe_fallback = fallback.replace("|", "")
    return f"{{{{tg_emoji:{custom_emoji_id}|{safe_fallback}}}}}"


def _utf16_index_to_py_index(value: str, target: int) -> int | None:
    units = 0
    for index, char in enumerate(value):
        if units == target:
            return index
        units += len(char.encode("utf-16-le")) // 2
        if units > target:
            return None
    return len(value) if units == target else None


def _source_metadata(
    *,
    message: Mapping[str, Any],
    telegram_chat_id: str,
    telegram_message_id: str,
) -> SourceMetadata:
    forward_origin = message.get("forward_origin")
    origin = _forward_origin(forward_origin if isinstance(forward_origin, Mapping) else None)
    if origin is None:
        origin = _legacy_forward_origin(message)
    source_url = origin.get("url") if origin is not None else None
    title = _source_title(origin)
    entities = _all_entities(message)
    return SourceMetadata(
        provider="telegram",
        provider_label="Telegram",
        external_id=f"{telegram_chat_id}:{telegram_message_id}",
        url=source_url,
        title=title,
        original_created_at=_iso_datetime(_origin_date(forward_origin, message)),
        origin=origin,
        author=_telegram_user(message.get("from")),
        group_id=str(message["media_group_id"]) if message.get("media_group_id") else None,
        entities=entities or None,
        custom_emoji_ids=_custom_emoji_ids(entities) or None,
        raw_payload=_json_safe(message),
        metadata={
            "telegram_chat_id": telegram_chat_id,
            "telegram_message_id": telegram_message_id,
            "forward_from": _json_safe(message.get("forward_from")),
            "forward_from_chat": _json_safe(message.get("forward_from_chat")),
            "forward_from_message_id": message.get("forward_from_message_id"),
            "forward_date": _iso_datetime(message.get("forward_date")),
        },
    )


def _forward_origin(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    origin_type = value.get("type")
    result: dict[str, Any] = {"type": origin_type} if origin_type else {}
    if origin_type == "channel" and isinstance(value.get("chat"), Mapping):
        chat = value["chat"]
        result.update(_telegram_chat(chat))
        if value.get("message_id") is not None:
            result["message_id"] = value["message_id"]
        username = chat.get("username")
        if username and value.get("message_id") is not None:
            result["url"] = f"https://t.me/{username}/{value['message_id']}"
    elif origin_type == "user":
        result.update(_telegram_user(value.get("sender_user")) or {})
    elif origin_type == "chat" and isinstance(value.get("sender_chat"), Mapping):
        result.update(_telegram_chat(value["sender_chat"]))
    elif origin_type == "hidden_user" and value.get("sender_user_name"):
        result["name"] = str(value["sender_user_name"])
    if value.get("date") is not None:
        result["date"] = _iso_datetime(value.get("date"))
    return result or None


def _legacy_forward_origin(message: Mapping[str, Any]) -> dict[str, Any] | None:
    forward_chat = message.get("forward_from_chat")
    if isinstance(forward_chat, Mapping):
        result = _telegram_chat(forward_chat)
        if message.get("forward_from_message_id") is not None:
            result["message_id"] = message["forward_from_message_id"]
        username = forward_chat.get("username")
        if username and message.get("forward_from_message_id") is not None:
            result["url"] = f"https://t.me/{username}/{message['forward_from_message_id']}"
        if message.get("forward_date") is not None:
            result["date"] = _iso_datetime(message.get("forward_date"))
        return result

    forward_user = message.get("forward_from")
    if isinstance(forward_user, Mapping):
        result = _telegram_user(forward_user) or {"type": "user"}
        if message.get("forward_date") is not None:
            result["date"] = _iso_datetime(message.get("forward_date"))
        return result

    forward_sender_name = message.get("forward_sender_name")
    if forward_sender_name:
        result = {"type": "hidden_user", "name": str(forward_sender_name)}
        if message.get("forward_date") is not None:
            result["date"] = _iso_datetime(message.get("forward_date"))
        return result

    return None


def _telegram_user(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    first_name = value.get("first_name")
    last_name = value.get("last_name")
    name = " ".join(str(part) for part in (first_name, last_name) if part)
    result = {
        "type": "user",
        "id": value.get("id"),
        "name": name or None,
        "username": value.get("username"),
    }
    return {key: val for key, val in result.items() if val is not None}


def _telegram_chat(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "type": value.get("type"),
        "id": value.get("id"),
        "title": value.get("title") or value.get("first_name"),
        "username": value.get("username"),
    }
    return {key: val for key, val in result.items() if val is not None}


def _source_title(origin: Mapping[str, Any] | None) -> str | None:
    if origin is None:
        return None
    value = origin.get("title") or origin.get("name") or origin.get("username")
    return str(value) if value else None


def _origin_date(forward_origin: object, message: Mapping[str, Any]) -> object:
    if isinstance(forward_origin, Mapping) and forward_origin.get("date") is not None:
        return forward_origin.get("date")
    return message.get("forward_date") or message.get("date")


def _all_entities(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for key in ("entities", "caption_entities"):
        raw = message.get(key)
        if isinstance(raw, list):
            entities.extend(_json_safe(item) for item in raw if isinstance(item, Mapping))
    return entities


def _custom_emoji_ids(entities: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for entity in entities:
        if entity.get("type") == "custom_emoji" and entity.get("custom_emoji_id") is not None:
            ids.append(str(entity["custom_emoji_id"]))
    return ids


def _iso_datetime(value: object) -> str | None:
    if isinstance(value, datetime):
        source = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return source.isoformat()
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC).isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _json_safe(value: object) -> Any:
    if isinstance(value, datetime):
        return _iso_datetime(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
