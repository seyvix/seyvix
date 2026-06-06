from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.texts.help import HELP

router = Router(name="help")


@router.message(Command("help"))
async def help_handler(message: Message, web_app_url: str | None = None) -> None:
    await message.answer(HELP, reply_markup=web_app_keyboard(web_app_url))
