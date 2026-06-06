from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from telegram_bot.domain.enums import BotMode


def mode_keyboard(
    *,
    current_mode: BotMode,
    has_active_collection: bool,
    web_app_url: str | None,
) -> InlineKeyboardMarkup:
    def label(mode: BotMode, text: str) -> str:
        return f"✓ {text}" if current_mode == mode else text

    rows = [
        [
            InlineKeyboardButton(
                text=label(BotMode.AUTO, "Авто"),
                callback_data="mode:auto",
            ),
            InlineKeyboardButton(
                text=label(BotMode.SEPARATE, "Всё отдельно"),
                callback_data="mode:separate",
            ),
        ],
        [
            InlineKeyboardButton(
                text=label(BotMode.MANUAL_COLLECTION, "Ручная коллекция"),
                callback_data="mode:manual_collection",
            )
        ],
    ]
    if has_active_collection:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Завершить коллекцию",
                    callback_data="collection:finish",
                )
            ]
        )
    if web_app_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Открыть Seyvix",
                    web_app=WebAppInfo(url=web_app_url),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
