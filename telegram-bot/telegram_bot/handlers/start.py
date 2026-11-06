from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import Message

from telegram_bot.bot.commands import show_admin_commands
from telegram_bot.domain.models import UserContext
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.texts.start import START_LINKED, START_UNLINKED

router = Router(name="start")
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def start_handler(
    message: Message,
    bot: Bot,
    user: UserContext,
    web_app_url: str | None = None,
) -> None:
    if user.is_admin:
        try:
            await show_admin_commands(bot, message.chat.id)
        except TelegramAPIError:
            logger.warning("Could not set admin commands", exc_info=True)
    text = START_LINKED if user.linked else START_UNLINKED
    await message.answer(text, reply_markup=web_app_keyboard(web_app_url))
