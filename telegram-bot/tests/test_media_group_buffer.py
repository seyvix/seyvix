from __future__ import annotations

import asyncio

from telegram_bot.domain.models import InboundMaterial, MaterialType, SavedMaterial, SourceMetadata
from telegram_bot.presentation.telegram.media_group_buffer import MediaGroupBuffer


def _material(message_id: str, *, caption: str | None = None) -> InboundMaterial:
    return InboundMaterial(
        telegram_user_id="100500",
        telegram_chat_id="9001",
        telegram_message_id=message_id,
        message_date=1_778_425_100,
        material_type=MaterialType.PHOTO,
        text=None,
        caption=caption,
        attachment=None,
        source=SourceMetadata(
            provider="telegram",
            provider_label="Telegram",
            external_id=f"9001:{message_id}",
            group_id="album-1",
        ),
    )


def test_media_group_buffer_saves_album_parts_and_answers_once() -> None:
    async def scenario() -> None:
        buffer = MediaGroupBuffer(flush_delay_seconds=0.01)
        saved_materials: list[InboundMaterial] = []
        answers: list[SavedMaterial] = []
        errors: list[Exception] = []

        async def save(material: InboundMaterial) -> SavedMaterial:
            saved_materials.append(material)
            return SavedMaterial(title=f"note-{material.telegram_message_id}")

        async def answer_saved(saved: SavedMaterial) -> None:
            answers.append(saved)

        async def answer_error(exc: Exception) -> None:
            errors.append(exc)

        await buffer.ingest(
            material=_material("31", caption="Caption"),
            save=save,
            answer_saved=answer_saved,
            answer_error=answer_error,
        )
        await buffer.ingest(
            material=_material("30", caption="Caption"),
            save=save,
            answer_saved=answer_saved,
            answer_error=answer_error,
        )
        await asyncio.sleep(0.05)

        assert [item.telegram_message_id for item in saved_materials] == ["30", "31"]
        assert [item.caption for item in saved_materials] == ["Caption", None]
        assert [answer.title for answer in answers] == ["note-31"]
        assert errors == []

    asyncio.run(scenario())


def test_media_group_buffer_saves_non_album_message_immediately() -> None:
    async def scenario() -> None:
        buffer = MediaGroupBuffer(flush_delay_seconds=60)
        saved_materials: list[InboundMaterial] = []
        answers: list[SavedMaterial] = []

        material = InboundMaterial(
            telegram_user_id="100500",
            telegram_chat_id="9001",
            telegram_message_id="1",
            message_date=1_778_425_100,
            material_type=MaterialType.TEXT,
            text="plain",
            caption=None,
            attachment=None,
        )

        async def save(material: InboundMaterial) -> SavedMaterial:
            saved_materials.append(material)
            return SavedMaterial(title="plain")

        async def answer_saved(saved: SavedMaterial) -> None:
            answers.append(saved)

        async def answer_error(exc: Exception) -> None:
            raise exc

        await buffer.ingest(
            material=material,
            save=save,
            answer_saved=answer_saved,
            answer_error=answer_error,
        )

        assert saved_materials == [material]
        assert [answer.title for answer in answers] == ["plain"]

    asyncio.run(scenario())
