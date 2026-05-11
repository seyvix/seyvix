from __future__ import annotations

from io import BytesIO

import httpx
from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from telegram_bot.application.use_cases import BotUseCases
from telegram_bot.presentation.telegram.keyboards import web_app_keyboard
from telegram_bot.presentation.telegram.media_group_buffer import MediaGroupBuffer
from telegram_bot.presentation.telegram.message_mapper import material_from_message


def build_router() -> Router:
    router = Router(name="telegram_ingest")

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def help_handler(message: Message, web_app_url: str | None = None) -> None:
        await message.answer(
            "Отправьте текст, ссылку, изображение или документ, чтобы сохранить материал.",
            reply_markup=web_app_keyboard(web_app_url),
        )

    @router.message(Command("app"))
    async def app_handler(message: Message, web_app_url: str | None = None) -> None:
        await message.answer("Открыть Seyvix", reply_markup=web_app_keyboard(web_app_url))

    @router.message(Command("mode"))
    async def mode_handler(message: Message) -> None:
        await message.answer("Доступны /default и /grouped.")

    @router.message(Command("default"))
    async def default_handler(message: Message, use_cases: BotUseCases) -> None:
        user_id = _telegram_user_id(message)
        if user_id is None:
            return
        await use_cases.switch_to_default_mode(user_id)
        await message.answer("Режим Default включен.")

    @router.message(Command("grouped"))
    async def grouped_handler(message: Message, use_cases: BotUseCases) -> None:
        user_id = _telegram_user_id(message)
        if user_id is None:
            return
        await use_cases.switch_to_grouped_mode(user_id)
        await message.answer("Режим GroupedNotes включен.")

    @router.message(Command("finish"))
    async def finish_handler(message: Message, use_cases: BotUseCases) -> None:
        user_id = _telegram_user_id(message)
        if user_id is None:
            return
        await use_cases.finish_collection(user_id)
        await message.answer("Коллекция завершена.")

    @router.message()
    async def ingest_handler(
        message: Message,
        bot: Bot,
        use_cases: BotUseCases,
        media_group_buffer: MediaGroupBuffer,
        web_app_url: str | None = None,
    ) -> None:
        material = material_from_message(message)
        if material is None:
            return
        if material.attachment is not None:
            material = material.with_attachment_data(
                await _download_attachment(bot, material.attachment.file_id)
            )
        await media_group_buffer.ingest(
            material=material,
            save=use_cases.ingest_material,
            answer_saved=lambda saved: message.answer(
                f"Сохранено: {saved.title}",
                reply_markup=web_app_keyboard(web_app_url),
            ),
            answer_error=lambda exc: _answer_ingest_error(message, exc, web_app_url),
        )

    return router


async def _download_attachment(bot: Bot, file_id: str) -> bytes:
    destination = BytesIO()
    await bot.download(file_id, destination=destination)
    return destination.getvalue()


async def _answer_backend_error(
    message: Message,
    exc: httpx.HTTPStatusError,
    web_app_url: str | None,
) -> None:
    if exc.response.status_code == 404:
        await message.answer(
            (
                "Telegram не привязан к аккаунту Seyvix. "
                "Откройте приложение и войдите через Telegram."
            ),
            reply_markup=web_app_keyboard(web_app_url),
        )
        return
    await message.answer("Не удалось сохранить материал.")


async def _answer_ingest_error(
    message: Message,
    exc: Exception,
    web_app_url: str | None,
) -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        await _answer_backend_error(message, exc, web_app_url)
        return
    await message.answer("Не удалось сохранить материал.")


def _telegram_user_id(message: Message) -> str | None:
    if message.from_user is None:
        return None
    return str(message.from_user.id)
