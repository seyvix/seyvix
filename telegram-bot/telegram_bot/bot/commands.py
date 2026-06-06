from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand


async def configure_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="начать работу"),
            BotCommand(command="mode", description="режим сохранения"),
            BotCommand(command="help", description="помощь"),
            BotCommand(command="finish", description="завершение коллекции в ручном режиме"),
        ]
    )
