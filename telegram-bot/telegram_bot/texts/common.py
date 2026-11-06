"""User-facing bot texts (HTML parse mode: escape dynamic values)."""

from __future__ import annotations

from html import escape

AUTH_REQUIRED = (
    "Я пока не знаю, к какому аккаунту Seyvix тебя привязать.\n\n"
    "Открой приложение и войди через Telegram — после этого можно будет сохранять "
    "материалы прямо сюда."
)

UNKNOWN_COMMAND = "Не понял команду.\n\nОсновные команды:\n/mode — режим сохранения\n/help — помощь"

UNSUPPORTED_MESSAGE = (
    "Я пока не умею сохранять такой тип сообщения.\n\n"
    "Можно отправить текст, ссылку, фото, видео, голосовое, аудио или документ."
)

BACKEND_UNAVAILABLE = (
    "Seyvix сейчас недоступен.\n\n"
    "Похоже, сервер перезапускается или временно не отвечает. Попробуй ещё раз через минуту."
)

SAVE_FAILED = (
    "Не получилось сохранить материал.\n\n"
    "Похоже, Seyvix временно недоступен. Попробуй ещё раз чуть позже."
)

FILE_TOO_LARGE = (
    "Не получилось сохранить файл: он слишком большой для Seyvix.\n\n"
    "Попробуй загрузить файл поменьше."
)

DOWNLOAD_FAILED = "Не удалось скачать файл из Telegram. Попробуй отправить его ещё раз."


def telegram_file_too_large(filename: str, limit_mb: int) -> str:
    return (
        f"Файл «{escape(filename)}» больше {limit_mb} МБ — Telegram не даёт ботам скачивать "
        "такие файлы.\n\nЗагрузи его через приложение Seyvix, остальное из сообщения я сохраню."
    )


def access_denied(telegram_user_id: int) -> str:
    return (
        "Доступ к Seyvix ограничен.\n\n"
        f"Твой Telegram ID: <code>{telegram_user_id}</code>\n"
        "Отправь его администратору, чтобы он открыл доступ."
    )
