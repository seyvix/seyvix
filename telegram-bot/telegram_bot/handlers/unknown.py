from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from telegram_bot.texts.common import UNKNOWN_COMMAND

router = Router(name="unknown")


@router.message(F.text.startswith("/"))
async def unknown_command_handler(message: Message) -> None:
    await message.answer(UNKNOWN_COMMAND)
