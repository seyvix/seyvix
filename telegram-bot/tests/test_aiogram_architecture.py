from __future__ import annotations

import asyncio

from aiogram import Dispatcher, Router

from telegram_bot.application.use_cases import BotUseCases
from telegram_bot.domain.models import InboundMaterial, MaterialType
from telegram_bot.presentation.telegram.factory import build_dispatcher
from telegram_bot.presentation.telegram.router import build_router


class FakeBackend:
    def __init__(self) -> None:
        self.ingested: list[InboundMaterial] = []
        self.modes: list[tuple[str, str]] = []
        self.finished: list[str] = []

    async def ingest(self, material: InboundMaterial) -> dict[str, object]:
        self.ingested.append(material)
        return {"note": {"title": "Saved note"}}

    async def set_mode(self, *, telegram_user_id: str, mode: str) -> None:
        self.modes.append((telegram_user_id, mode))

    async def finish_collection(self, *, telegram_user_id: str) -> None:
        self.finished.append(telegram_user_id)


def test_bot_composition_uses_aiogram_dispatcher_and_router() -> None:
    use_cases = BotUseCases(backend=FakeBackend())

    router = build_router()
    dispatcher = build_dispatcher(use_cases=use_cases, web_app_url="https://app.example.com")

    assert isinstance(router, Router)
    assert isinstance(dispatcher, Dispatcher)


def test_use_case_sends_inbound_material_to_backend() -> None:
    backend = FakeBackend()
    use_cases = BotUseCases(backend=backend)
    material = InboundMaterial(
        telegram_user_id="100500",
        telegram_chat_id="700",
        telegram_message_id="15",
        message_date=1_777_777_777,
        material_type=MaterialType.TEXT,
        text="Markdown **note**",
        caption=None,
        attachment=None,
    )

    result = asyncio.run(use_cases.ingest_material(material))

    assert result.title == "Saved note"
    assert backend.ingested == [material]
