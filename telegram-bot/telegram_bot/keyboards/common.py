from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def web_app_keyboard(web_app_url: str | None) -> InlineKeyboardMarkup | None:
    if not web_app_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть Seyvix",
                    web_app=WebAppInfo(url=web_app_url),
                )
            ]
        ]
    )
