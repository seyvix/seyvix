from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState, InboundMaterial, SavedMaterial
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend
from telegram_bot.services.state import BotStateRepository

StatusMessage = TypeVar("StatusMessage")
SendLoading = Callable[[InboundMaterial], Awaitable[StatusMessage]]
PrepareMaterial = Callable[[InboundMaterial, StatusMessage | None], Awaitable[InboundMaterial]]
UpdateSaved = Callable[[StatusMessage, SavedMaterial], Awaitable[None]]
UpdateError = Callable[[StatusMessage, Exception], Awaitable[None]]
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Bucket:
    state: BotState
    materials: list[InboundMaterial]
    status: object
    task: asyncio.Task[None]
    pending: int = 0


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
        send_loading: SendLoading[StatusMessage],
        prepare_material: PrepareMaterial[StatusMessage],
        update_saved: UpdateSaved[StatusMessage],
        update_error: UpdateError[StatusMessage],
    ) -> None:
        key = self._buffer_key(material=material, state=state)
        logger.info(
            "Telegram ingest queued user=%s chat=%s message=%s mode=%s type=%s key=%s",
            material.telegram_user_id,
            material.telegram_chat_id,
            material.telegram_message_id,
            state.mode.value,
            material.material_type.value,
            key or "immediate",
        )
        if key is None:
            status = await send_loading(material)
            try:
                prepared = await prepare_material(material, status)
            except Exception as exc:
                logger.exception(
                    "Telegram material prepare failed user=%s chat=%s message=%s",
                    material.telegram_user_id,
                    material.telegram_chat_id,
                    material.telegram_message_id,
                )
                await update_error(status, exc)
                return
            await self._save_and_update(
                status=status,
                state=state,
                materials=[prepared],
                update_saved=update_saved,
                update_error=update_error,
            )
            return

        bucket = self._buckets.get(key)
        if bucket is None:
            prepare_status: StatusMessage | None = await send_loading(material)
            placeholder = asyncio.create_task(asyncio.sleep(0))
            bucket = _Bucket(
                state=state,
                materials=[],
                status=prepare_status,
                task=placeholder,
            )
            self._buckets[key] = bucket
            logger.info("Telegram ingest bucket opened key=%s", key)
        else:
            bucket.task.cancel()
            prepare_status = None

        bucket.pending += 1
        try:
            prepared = await prepare_material(material, prepare_status)
        except Exception as exc:
            bucket.pending -= 1
            current_bucket = self._buckets.pop(key, None)
            if current_bucket is not None:
                current_bucket.task.cancel()
            logger.exception(
                "Telegram bucket material prepare failed key=%s user=%s chat=%s message=%s",
                key,
                material.telegram_user_id,
                material.telegram_chat_id,
                material.telegram_message_id,
            )
            await update_error(cast(StatusMessage, bucket.status), exc)
            return

        bucket.materials.append(prepared)
        bucket.pending -= 1
        bucket.task.cancel()
        logger.info(
            "Telegram ingest bucket appended key=%s count=%s pending=%s",
            key,
            len(bucket.materials),
            bucket.pending,
        )
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
        if bucket.pending > 0:
            self._buckets[key] = bucket
            bucket.task = asyncio.create_task(
                self._flush_later(
                    key=key,
                    delay=delay,
                    update_saved=update_saved,
                    update_error=update_error,
                )
            )
            logger.info(
                "Telegram ingest bucket flush postponed key=%s pending=%s",
                key,
                bucket.pending,
            )
            return
        logger.info(
            "Telegram ingest bucket flushing key=%s count=%s",
            key,
            len(bucket.materials),
        )
        await self._save_and_update(
            status=cast(StatusMessage, bucket.status),
            state=bucket.state,
            materials=_deduplicate_repeated_captions(_sort_materials(bucket.materials)),
            update_saved=update_saved,
            update_error=update_error,
        )

    async def _save_and_update(
        self,
        *,
        status: StatusMessage,
        state: BotState,
        materials: list[InboundMaterial],
        update_saved: UpdateSaved[StatusMessage],
        update_error: UpdateError[StatusMessage],
    ) -> None:
        try:
            saved = await self._save_materials(state=state, materials=materials)
        except Exception as exc:
            first = materials[0] if materials else None
            logger.exception(
                "Telegram ingest save failed user=%s chat=%s mode=%s count=%s",
                first.telegram_user_id if first else None,
                first.telegram_chat_id if first else None,
                state.mode.value,
                len(materials),
            )
            await update_error(status, exc)
            return
        first = materials[0]
        logger.info(
            "Telegram ingest saved user=%s chat=%s mode=%s count=%s saved_id=%s status=%s",
            first.telegram_user_id,
            first.telegram_chat_id,
            state.mode.value,
            len(materials),
            saved.id,
            saved.status,
        )
        await update_saved(status, saved)

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
        if state.mode == BotMode.AUTO:
            return f"auto:{material.telegram_user_id}:{material.telegram_chat_id}"
        media_group_key = self._media_group_key(material)
        if media_group_key is not None:
            return media_group_key
        return None

    def _buffer_delay(self, *, material: InboundMaterial, state: BotState) -> float:
        if state.mode == BotMode.AUTO:
            return self.auto_group_window_seconds
        if self._media_group_key(material) is not None:
            return self.media_group_flush_seconds
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
