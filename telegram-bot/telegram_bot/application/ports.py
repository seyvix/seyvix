from __future__ import annotations

from typing import Protocol

from telegram_bot.domain.models import InboundMaterial


class SeyvixBackendPort(Protocol):
    async def ingest(self, material: InboundMaterial) -> dict[str, object]:
        raise NotImplementedError

    async def set_mode(self, *, telegram_user_id: str, mode: str) -> None:
        raise NotImplementedError

    async def finish_collection(self, *, telegram_user_id: str) -> None:
        raise NotImplementedError
