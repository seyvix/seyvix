from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TypeVar

from telegram_bot.domain.models import InboundMaterial, SavedMaterial

StatusMessage = TypeVar("StatusMessage")
SaveMaterial = Callable[[InboundMaterial], Awaitable[SavedMaterial]]
SendLoading = Callable[[InboundMaterial], Awaitable[StatusMessage]]
UpdateSaved = Callable[[StatusMessage, SavedMaterial], Awaitable[None]]
UpdateError = Callable[[StatusMessage, Exception], Awaitable[None]]


class MediaGroupBuffer:
    def __init__(self, *, flush_delay_seconds: float) -> None:
        self.flush_delay_seconds = flush_delay_seconds
        self._buckets: dict[str, list[InboundMaterial]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._statuses: dict[str, object] = {}

    async def ingest(
        self,
        *,
        material: InboundMaterial,
        save: SaveMaterial,
        send_loading: SendLoading[StatusMessage],
        update_saved: UpdateSaved[StatusMessage],
        update_error: UpdateError[StatusMessage],
    ) -> None:
        key = self._group_key(material)
        if key is None:
            status = await send_loading(material)
            try:
                saved = await save(material)
            except Exception as exc:
                await update_error(status, exc)
                return
            await update_saved(status, saved)
            return

        if key not in self._buckets:
            self._statuses[key] = await send_loading(material)
        self._buckets.setdefault(key, []).append(material)
        previous = self._tasks.pop(key, None)
        if previous is not None:
            previous.cancel()
        self._tasks[key] = asyncio.create_task(
            self._flush_later(
                key=key,
                save=save,
                update_saved=update_saved,
                update_error=update_error,
            )
        )

    async def _flush_later(
        self,
        *,
        key: str,
        save: SaveMaterial,
        update_saved: UpdateSaved[StatusMessage],
        update_error: UpdateError[StatusMessage],
    ) -> None:
        try:
            await asyncio.sleep(self.flush_delay_seconds)
        except asyncio.CancelledError:
            return

        materials = self._buckets.pop(key, [])
        status = self._statuses.pop(key, None)
        self._tasks.pop(key, None)
        if not materials or status is None:
            return

        saved: SavedMaterial | None = None
        try:
            for material in _deduplicate_repeated_captions(_sort_materials(materials)):
                saved = await save(material)
        except Exception as exc:
            await update_error(status, exc)
            return

        if saved is not None:
            await update_saved(status, saved)

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
