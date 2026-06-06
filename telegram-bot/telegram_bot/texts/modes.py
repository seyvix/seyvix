from __future__ import annotations

from telegram_bot.domain.enums import BotMode

MODE_LABELS = {
    BotMode.AUTO: "Авто",
    BotMode.SEPARATE: "Всё отдельно",
    BotMode.MANUAL_COLLECTION: "Ручная коллекция",
}


def mode_menu_text(mode: BotMode) -> str:
    return (
        "Режим сохранения\n\n"
        "Авто — одиночные материалы отдельно, альбомы и быстрые серии вместе.\n"
        "Всё отдельно — каждое сообщение отдельно, альбомы сохраняются альбомами.\n"
        "Ручная коллекция — собираю материалы вместе до /finish.\n\n"
        f"Текущий режим: {MODE_LABELS[mode]}"
    )


def settings_text(mode: BotMode) -> str:
    return (
        "Настройки Seyvix Bot\n\n"
        f"Текущий режим: {MODE_LABELS[mode]}\n\n"
        "Режим можно изменить через /mode. Остальное управление — в Web App."
    )


def mode_enabled_text(mode: BotMode) -> str:
    if mode == BotMode.AUTO:
        return (
            "Режим Авто включён.\n\n"
            "Одиночные материалы сохраню отдельно. Альбомы и быстрые серии объединю."
        )
    if mode == BotMode.SEPARATE:
        return (
            "Режим «Всё отдельно» включён.\n\n"
            "Каждое новое сообщение сохраню отдельным материалом."
        )
    return (
        "Ручная коллекция включена.\n\n"
        "Отправляй материалы — я соберу их вместе. Когда закончишь, нажми /finish."
    )


FINISH_DONE = "Коллекция завершена. Я вернул режим Авто."
FINISH_EMPTY = (
    "Сейчас нет активной коллекции.\n\n" "Включи ручную коллекцию через /mode и отправь материалы."
)
MANUAL_COLLECTION_REMINDER = (
    "Кажется, коллекция ещё открыта.\n\n"
    "Когда закончишь, нажми /finish — я завершу подборку и верну режим Авто."
)
