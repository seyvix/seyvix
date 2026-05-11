from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from telegram_bot.domain.models import InboundMaterial, SavedMaterial

SaveMaterial = Callable[[InboundMaterial], Awaitable[SavedMaterial]]
AnswerSaved = Callable[[SavedMaterial], Awaitable[None]]
AnswerError = Callable[[Exception], Awaitable[None]]


class MediaGroupBuffer:
    def __init__(self, *, flush_delay_seconds: float) -> None:
        self.flush_delay_seconds = flush_delay_seconds
        self._buckets: dict[str, list[InboundMaterial]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def ingest(
        self,
        *,
        material: InboundMaterial,
        save: SaveMaterial,
        answer_saved: AnswerSaved,
        answer_error: AnswerError,
    ) -> None:
        key = self._group_key(material)
        if key is None:
            try:
                saved = await save(material)
            except Exception as exc:
                await answer_error(exc)
                return
            await answer_saved(saved)
            return

        self._buckets.setdefault(key, []).append(material)
        previous = self._tasks.pop(key, None)
        if previous is not None:
            previous.cancel()
        self._tasks[key] = asyncio.create_task(
            self._flush_later(
                key=key,
                save=save,
                answer_saved=answer_saved,
                answer_error=answer_error,
            )
        )

    async def _flush_later(
        self,
        *,
        key: str,
        save: SaveMaterial,
        answer_saved: AnswerSaved,
        answer_error: AnswerError,
    ) -> None:
        try:
            await asyncio.sleep(self.flush_delay_seconds)
        except asyncio.CancelledError:
            return

        materials = self._buckets.pop(key, [])
        self._tasks.pop(key, None)
        if not materials:
            return

        saved: SavedMaterial | None = None
        try:
            for material in _deduplicate_repeated_captions(_sort_materials(materials)):
                saved = await save(material)
        except Exception as exc:
            await answer_error(exc)
            return

        if saved is not None:
            await answer_saved(saved)

    @staticmethod
    def _group_key(material: InboundMaterial) -> str | None:
        if material.source is None or not material.source.group_id:
            return None
        return ":".join(
            [
                material.source.provider,
                material.telegram_user_id,
                material.telegram_chat_id,
                material.source.group_id,
            ]
        )


def _sort_materials(materials: list[InboundMaterial]) -> list[InboundMaterial]:
    return sorted(materials, key=lambda item: _message_id_sort_key(item.telegram_message_id))


def _message_id_sort_key(value: str) -> tuple[int, str]:
    return (int(value), value) if value.isdecimal() else (0, value)


def _deduplicate_repeated_captions(materials: list[InboundMaterial]) -> list[InboundMaterial]:
    seen: set[str] = set()
    result: list[InboundMaterial] = []
    for material in materials:
        caption = material.caption.strip() if material.caption else None
        if caption and caption in seen:
            result.append(replace(material, caption=None))
            continue
        if caption:
            seen.add(caption)
        result.append(material)
    return result
