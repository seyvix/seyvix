from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonWebApp, WebAppInfo

USER_COMMANDS = [
    BotCommand(command="start", description="начать работу"),
    BotCommand(command="mode", description="режим сохранения"),
    BotCommand(command="finish", description="завершить ручную коллекцию"),
    BotCommand(command="help", description="помощь"),
]
ADMIN_COMMANDS = [
    *USER_COMMANDS,
    BotCommand(command="allow", description="открыть доступ: id или @username"),
    BotCommand(command="deny", description="закрыть доступ"),
    BotCommand(command="access", description="список доступа"),
]


async def configure_bot(bot: Bot, *, web_app_url: str | None) -> None:
    await bot.set_my_commands(USER_COMMANDS)
    if web_app_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Seyvix", web_app=WebAppInfo(url=web_app_url)),
        )


async def show_admin_commands(bot: Bot, chat_id: int) -> None:
    """Admins are known only to the backend; their command menu is set when they /start."""
    await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))
