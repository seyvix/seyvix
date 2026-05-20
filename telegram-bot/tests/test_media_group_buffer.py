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
        loading: list[str] = []
        saved_updates: list[tuple[str, SavedMaterial]] = []
        errors: list[Exception] = []

        async def save(material: InboundMaterial) -> SavedMaterial:
            saved_materials.append(material)
            return SavedMaterial(title=f"note-{material.telegram_message_id}")

        async def send_loading(material: InboundMaterial) -> str:
            loading.append(material.telegram_message_id)
            return f"status-{material.telegram_message_id}"

        async def update_saved(status: str, saved: SavedMaterial) -> None:
            saved_updates.append((status, saved))

        async def update_error(status: str, exc: Exception) -> None:
            errors.append(exc)

        await buffer.ingest(
            material=_material("31", caption="Caption"),
            save=save,
            send_loading=send_loading,
            update_saved=update_saved,
            update_error=update_error,
        )
        assert loading == ["31"]
        assert saved_materials == []

        await buffer.ingest(
            material=_material("30", caption="Caption"),
            save=save,
            send_loading=send_loading,
            update_saved=update_saved,
            update_error=update_error,
        )
        await asyncio.sleep(0.05)

        assert loading == ["31"]
        assert [item.telegram_message_id for item in saved_materials] == ["30", "31"]
        assert [item.caption for item in saved_materials] == ["Caption", None]
        assert [(status, saved.title) for status, saved in saved_updates] == [
            ("status-31", "note-31")
        ]
        assert errors == []

    asyncio.run(scenario())


def test_media_group_buffer_saves_non_album_message_immediately() -> None:
    async def scenario() -> None:
        buffer = MediaGroupBuffer(flush_delay_seconds=60)
        saved_materials: list[InboundMaterial] = []
        loading: list[str] = []
        saved_updates: list[tuple[str, SavedMaterial]] = []

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

        async def send_loading(material: InboundMaterial) -> str:
            loading.append(material.telegram_message_id)
            return f"status-{material.telegram_message_id}"

        async def update_saved(status: str, saved: SavedMaterial) -> None:
            saved_updates.append((status, saved))

        async def update_error(status: str, exc: Exception) -> None:
            raise exc

        await buffer.ingest(
            material=material,
            save=save,
            send_loading=send_loading,
            update_saved=update_saved,
            update_error=update_error,
        )

        assert loading == ["1"]
        assert saved_materials == [material]
        assert [(status, saved.title) for status, saved in saved_updates] == [("status-1", "plain")]

    asyncio.run(scenario())
