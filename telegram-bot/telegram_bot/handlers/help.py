from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from telegram_bot.domain.models import UserContext
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.texts.help import ADMIN_HELP, HELP

router = Router(name="help")


@router.message(Command("help"))
async def help_handler(
    message: Message,
    user: UserContext,
    web_app_url: str | None = None,
) -> None:
    text = f"{HELP}\n\n{ADMIN_HELP}" if user.is_admin else HELP
    await message.answer(text, reply_markup=web_app_keyboard(web_app_url))
