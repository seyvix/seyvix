from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from telegram_bot.application.ports import SeyvixBackendPort
from telegram_bot.domain.models import InboundMaterial, IngestMode, SavedMaterial


@dataclass(frozen=True, slots=True)
class BotUseCases:
    backend: SeyvixBackendPort

    async def ingest_material(self, material: InboundMaterial) -> SavedMaterial:
        payload = await self.backend.ingest(material)
        raw_note = payload.get("note")
        note = raw_note if isinstance(raw_note, Mapping) else {}
        title = _string_value(note, "title") or "материал"
        return SavedMaterial(title=title)

    async def switch_to_default_mode(self, telegram_user_id: str) -> None:
        await self.backend.set_mode(
            telegram_user_id=telegram_user_id,
            mode=IngestMode.DEFAULT.value,
        )

    async def switch_to_grouped_mode(self, telegram_user_id: str) -> None:
        await self.backend.set_mode(
            telegram_user_id=telegram_user_id,
            mode=IngestMode.GROUPED_NOTES.value,
        )

    async def finish_collection(self, telegram_user_id: str) -> None:
        await self.backend.finish_collection(telegram_user_id=telegram_user_id)


def _string_value(mapping: Mapping[Any, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None
