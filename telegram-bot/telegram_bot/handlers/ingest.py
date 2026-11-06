from __future__ import annotations

import logging
from html import escape
from typing import Any

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from telegram_bot.bot.middlewares import UserStatusCache
from telegram_bot.config import TELEGRAM_MAX_DOWNLOAD_BYTES
from telegram_bot.domain.models import InboundMaterial, SavedMaterial, UserContext
from telegram_bot.infrastructure.backend_client import BackendError, BackendUnavailableError
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.services.ingest import TelegramIngestService
from telegram_bot.services.message_mapper import material_from_message
from telegram_bot.services.state import BotStateService
from telegram_bot.texts.common import (
    AUTH_REQUIRED,
    BACKEND_UNAVAILABLE,
    DOWNLOAD_FAILED,
    FILE_TOO_LARGE,
    SAVE_FAILED,
    UNSUPPORTED_MESSAGE,
    access_denied,
    telegram_file_too_large,
)
from telegram_bot.texts.success import loading_text, saved_text

router = Router(name="ingest")
logger = logging.getLogger(__name__)


class ChatReporter:
    """Edits the "saving…" reply of the first message of a save with the outcome."""

    def __init__(
        self,
        message: Message,
        *,
        web_app_url: str | None,
        status_cache: UserStatusCache,
    ) -> None:
        self.message = message
        self.web_app_url = web_app_url
        self.status_cache = status_cache

    async def loading(self, material: InboundMaterial) -> Message:
        return await self.message.reply(loading_text(material))

    async def saved(self, status: Any, saved: SavedMaterial, skipped: list[str]) -> None:
        await self._show(status, escape(saved_text(saved)))
        await self._report_skipped(skipped)

    async def nothing_saved(self, status: Any, skipped: list[str]) -> None:
        await self._show(status, FILE_TOO_LARGE if not skipped else self._skipped_text(skipped))

    async def failed(self, status: Any, exc: Exception) -> None:
        await self._show(status, self._error_text(exc))

    async def _report_skipped(self, skipped: list[str]) -> None:
        if skipped:
            await self.message.answer(self._skipped_text(skipped))

    @staticmethod
    def _skipped_text(skipped: list[str]) -> str:
        limit_mb = TELEGRAM_MAX_DOWNLOAD_BYTES // (1024 * 1024)
        return "\n\n".join(telegram_file_too_large(name, limit_mb) for name in skipped[:5])

    def _error_text(self, exc: Exception) -> str:
        if isinstance(exc, BackendUnavailableError):
            return BACKEND_UNAVAILABLE
        if isinstance(exc, BackendError):
            if exc.code == "access_denied":
                self.status_cache.invalidate(self._user_id())
                return access_denied(self._user_id())
            if exc.code == "telegram_user_not_linked":
                self.status_cache.invalidate(self._user_id())
                return AUTH_REQUIRED
            if exc.status_code == 413:
                return FILE_TOO_LARGE
            return SAVE_FAILED
        if isinstance(exc, TelegramAPIError | OSError | TimeoutError):
            return DOWNLOAD_FAILED
        return SAVE_FAILED

    def _user_id(self) -> int:
        return self.message.from_user.id if self.message.from_user else self.message.chat.id

    async def _show(self, status: Any, text: str) -> None:
        markup = web_app_keyboard(self.web_app_url)
        if isinstance(status, Message):
            try:
                await status.edit_text(text, reply_markup=markup)
                return
            except TelegramAPIError:
                logger.info("Status message could not be edited; sending a new one")
        await self.message.answer(text, reply_markup=markup)


@router.message()
async def ingest_handler(
    message: Message,
    user: UserContext,
    state_service: BotStateService,
    ingest_service: TelegramIngestService,
    status_cache: UserStatusCache,
    web_app_url: str | None = None,
) -> None:
    if not user.linked:
        await message.answer(AUTH_REQUIRED, reply_markup=web_app_keyboard(web_app_url))
        return
    material = material_from_message(message)
    if material is None:
        await message.answer(UNSUPPORTED_MESSAGE, reply_markup=web_app_keyboard(web_app_url))
        return
    try:
        mode = await state_service.get_mode(user.telegram_user_id)
    except (BackendUnavailableError, BackendError):
        await message.answer(BACKEND_UNAVAILABLE)
        return
    await ingest_service.submit(
        material,
        mode=mode,
        reporter=ChatReporter(message, web_app_url=web_app_url, status_cache=status_cache),
    )
