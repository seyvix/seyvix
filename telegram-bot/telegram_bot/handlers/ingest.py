from __future__ import annotations

import logging
from base64 import b64encode
from dataclasses import replace
from html import escape
from io import BytesIO

import httpx
from aiogram import Bot, Router
from aiogram.types import Message, Sticker

from telegram_bot.domain.models import InboundMaterial, SavedMaterial, UserContext
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.services.ingest import TelegramIngestService
from telegram_bot.services.message_mapper import material_from_message
from telegram_bot.services.modes import ModeService
from telegram_bot.texts.common import (
    AUTH_REQUIRED,
    BACKEND_UNAVAILABLE,
    DOWNLOAD_FAILED,
    FILE_TOO_LARGE,
    UNSUPPORTED_MESSAGE,
)
from telegram_bot.texts.success import loading_text, saved_text

router = Router(name="ingest")
logger = logging.getLogger(__name__)


@router.message()
async def ingest_handler(
    message: Message,
    bot: Bot,
    mode_service: ModeService,
    ingest_service: TelegramIngestService,
    user_context: UserContext | None = None,
    web_app_url: str | None = None,
    telegram_user_id: str | None = None,
) -> None:
    if user_context is None or not user_context.linked or telegram_user_id is None:
        await message.answer(AUTH_REQUIRED, reply_markup=web_app_keyboard(web_app_url))
        return

    material = material_from_message(message)
    if material is None:
        await message.answer(UNSUPPORTED_MESSAGE, reply_markup=web_app_keyboard(web_app_url))
        return

    status_message = await message.reply(
        loading_text(material),
        reply_markup=web_app_keyboard(web_app_url),
    )

    material = await _with_custom_emoji_assets(bot, material)
    attachment = material.attachment
    if attachment is not None:
        try:
            material = material.with_attachment_data(
                await _download_attachment(bot, attachment.file_id)
            )
        except Exception as exc:
            logger.exception(
                "Failed to download Telegram attachment for user=%s chat=%s message=%s file_id=%s",
                material.telegram_user_id,
                material.telegram_chat_id,
                material.telegram_message_id,
                attachment.file_id,
            )
            await status_message.edit_text(
                _download_error_text(exc),
                reply_markup=web_app_keyboard(web_app_url),
            )
            return

    state = await mode_service.get_state(telegram_user_id)

    async def update_saved_status(status_message: Message, saved: SavedMaterial) -> None:
        await status_message.edit_text(
            escape(saved_text(saved)),
            reply_markup=web_app_keyboard(web_app_url),
        )

    await ingest_service.ingest(
        material=material,
        state=state,
        status=status_message,
        update_saved=update_saved_status,
        update_error=lambda status_message, exc: _edit_ingest_error(
            status_message,
            exc,
            web_app_url,
        ),
    )


async def _download_attachment(bot: Bot, file_id: str) -> bytes:
    destination = BytesIO()
    await bot.download(file_id, destination=destination)
    return destination.getvalue()


def _download_error_text(exc: Exception) -> str:
    message = str(exc).lower()
    if "too big" in message or "too large" in message or "file size" in message:
        return FILE_TOO_LARGE
    return DOWNLOAD_FAILED


async def _with_custom_emoji_assets(bot: Bot, material: InboundMaterial) -> InboundMaterial:
    source = material.source
    if source is None or not source.custom_emoji_ids:
        return material
    try:
        stickers = await bot.get_custom_emoji_stickers(source.custom_emoji_ids)
    except Exception:
        return material

    assets = {}
    for sticker in stickers:
        custom_emoji_id = sticker.custom_emoji_id
        if not custom_emoji_id:
            continue
        file_id = _sticker_preview_file_id(sticker)
        if not file_id:
            continue
        try:
            data = await _download_attachment(bot, file_id)
        except Exception:
            continue
        data_url = (
            f"data:{_sticker_preview_mime_type(sticker)};base64," f"{b64encode(data).decode()}"
        )
        assets[custom_emoji_id] = {
            "data_url": data_url,
            "fallback": sticker.emoji,
        }

    if not assets:
        return material
    metadata = dict(source.metadata or {})
    metadata["custom_emoji_assets"] = assets
    return replace(material, source=replace(source, metadata=metadata))


def _sticker_preview_file_id(sticker: Sticker) -> str | None:
    if sticker.thumbnail is not None:
        return sticker.thumbnail.file_id
    return sticker.file_id


def _sticker_preview_mime_type(sticker: Sticker) -> str:
    if sticker.thumbnail is not None:
        return "image/webp"
    if sticker.is_video:
        return "video/webm"
    if sticker.is_animated:
        return "application/x-tgsticker"
    return "image/webp"


async def _edit_ingest_error(
    status_message: Message,
    exc: Exception,
    web_app_url: str | None,
) -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 404:
            await status_message.edit_text(
                AUTH_REQUIRED,
                reply_markup=web_app_keyboard(web_app_url),
            )
            return
        if exc.response.status_code == 413:
            await status_message.edit_text(
                FILE_TOO_LARGE,
                reply_markup=web_app_keyboard(web_app_url),
            )
            return
    await status_message.edit_text(
        BACKEND_UNAVAILABLE,
        reply_markup=web_app_keyboard(web_app_url),
    )
