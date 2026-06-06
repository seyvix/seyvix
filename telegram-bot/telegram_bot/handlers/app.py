from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from telegram_bot.keyboards.common import web_app_keyboard

router = Router(name="app")


@router.message(Command("app"))
async def app_handler(message: Message, web_app_url: str | None = None) -> None:
    await message.answer("Открыть Seyvix:", reply_markup=web_app_keyboard(web_app_url))
