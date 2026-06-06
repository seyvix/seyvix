from __future__ import annotations

from telegram_bot.domain.models import InboundMaterial, MaterialType, SavedMaterial


def loading_text(material: InboundMaterial) -> str:
    if material.material_type == MaterialType.LINK:
        return "Сохраняю ссылку…"
    if material.material_type == MaterialType.AUDIO and material.attachment is not None:
        filename = material.attachment.filename.lower()
        if "voice" in filename or filename.endswith(".ogg"):
            return "Загружаю голосовое…"
    if material.attachment is not None:
        return "Загружаю и сохраняю…"
    return "Сохраняю…"


def saved_text(saved: SavedMaterial) -> str:
    if saved.status == "collection_updated":
        return f"Добавлено в коллекцию к: {saved.title}" if saved.title else "Добавлено в коллекцию."
    if saved.status == "collection_started":
        return f"Коллекция начата: {saved.title}" if saved.title else "Коллекция начата."
    return f"Сохранено: {saved.title}" if saved.title else "Сохранено."
