from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState, InboundMaterial, SavedMaterial
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend
from telegram_bot.services.state import BotStateRepository

StatusMessage = TypeVar("StatusMessage")
UpdateSaved = Callable[[StatusMessage, SavedMaterial], Awaitable[None]]
UpdateError = Callable[[StatusMessage, Exception], Awaitable[None]]


@dataclass(slots=True)
class _Bucket:
    state: BotState
    materials: list[InboundMaterial]
    statuses: list[object]
    task: asyncio.Task[None]


class TelegramIngestService:
    def __init__(
        self,
        *,
        backend: HttpSeyvixBackend,
        state_repository: BotStateRepository,
        auto_group_window_seconds: float,
        media_group_flush_seconds: float,
    ) -> None:
        self.backend = backend
        self.state_repository = state_repository
        self.auto_group_window_seconds = auto_group_window_seconds
        self.media_group_flush_seconds = media_group_flush_seconds
        self._buckets: dict[str, _Bucket] = {}

    async def ingest(
        self,
        *,
        material: InboundMaterial,
        state: BotState,
        status: StatusMessage,
        update_saved: UpdateSaved[StatusMessage],
        update_error: UpdateError[StatusMessage],
    ) -> None:
        key = self._buffer_key(material=material, state=state)
        if key is None:
            await self._save_and_update(
                statuses=[status],
                state=state,
                materials=[material],
                update_saved=update_saved,
                update_error=update_error,
            )
            return

        bucket = self._buckets.get(key)
        if bucket is None:
            placeholder = asyncio.create_task(asyncio.sleep(0))
            bucket = _Bucket(state=state, materials=[], statuses=[], task=placeholder)
            self._buckets[key] = bucket
        else:
            bucket.task.cancel()

        bucket.materials.append(material)
        bucket.statuses.append(status)
        bucket.task = asyncio.create_task(
            self._flush_later(
                key=key,
                delay=self._buffer_delay(material=material, state=state),
                update_saved=update_saved,
                update_error=update_error,
            )
        )

    async def _flush_later(
        self,
        *,
        key: str,
        delay: float,
        update_saved: UpdateSaved[StatusMessage],
        update_error: UpdateError[StatusMessage],
    ) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        bucket = self._buckets.pop(key, None)
        if bucket is None:
            return
        await self._save_and_update(
            statuses=[cast(StatusMessage, status) for status in bucket.statuses],
            state=bucket.state,
            materials=_deduplicate_repeated_captions(_sort_materials(bucket.materials)),
            update_saved=update_saved,
            update_error=update_error,
        )

    async def _save_and_update(
        self,
        *,
        statuses: list[StatusMessage],
        state: BotState,
        materials: list[InboundMaterial],
        update_saved: UpdateSaved[StatusMessage],
        update_error: UpdateError[StatusMessage],
    ) -> None:
        try:
            saved = await self._save_materials(state=state, materials=materials)
        except Exception as exc:
            await asyncio.gather(*(update_error(status, exc) for status in statuses))
            return
        await asyncio.gather(*(update_saved(status, saved) for status in statuses))

    async def _save_materials(
        self,
        *,
        state: BotState,
        materials: list[InboundMaterial],
    ) -> SavedMaterial:
        target_collection_id = (
            state.active_collection_id if state.mode == BotMode.MANUAL_COLLECTION else None
        )
        saved: SavedMaterial | None = None
        for material in materials:
            payload = await self.backend.ingest(material, target_collection_id=target_collection_id)
            saved = _saved_from_payload(payload)
            if saved.id is not None:
                target_collection_id = saved.id

        if saved is None:
            raise RuntimeError("No Telegram materials to save.")

        if state.mode == BotMode.MANUAL_COLLECTION and saved.id is not None:
            await self.state_repository.save(
                state.with_manual_collection(collection_id=saved.id, now=datetime.now(UTC))
            )
        return saved

    def _buffer_key(self, *, material: InboundMaterial, state: BotState) -> str | None:
        media_group_key = self._media_group_key(material)
        if media_group_key is not None:
            return media_group_key
        if state.mode == BotMode.AUTO:
            return f"auto:{material.telegram_user_id}:{material.telegram_chat_id}"
        return None

    def _buffer_delay(self, *, material: InboundMaterial, state: BotState) -> float:
        if self._media_group_key(material) is not None:
            return self.media_group_flush_seconds
        if state.mode == BotMode.AUTO:
            return self.auto_group_window_seconds
        return 0

    @staticmethod
    def _media_group_key(material: InboundMaterial) -> str | None:
        if material.source is None or not material.source.group_id:
            return None
        return ":".join(
            [
                "media",
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
    from dataclasses import replace

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


def _saved_from_payload(payload: Mapping[str, object]) -> SavedMaterial:
    raw_note = payload.get("note")
    note = raw_note if isinstance(raw_note, Mapping) else {}
    return SavedMaterial(
        title=_string_value(note, "title") or "материал",
        id=_string_value(note, "id"),
        status=_string_value(payload, "status") or "saved",
    )


def _string_value(mapping: Mapping[Any, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None
