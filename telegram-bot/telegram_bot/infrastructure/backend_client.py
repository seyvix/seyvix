from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from telegram_bot.domain.models import InboundMaterial


class HttpSeyvixBackend:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        internal_token: str,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token

    async def ingest(self, material: InboundMaterial) -> dict[str, object]:
        data = {
            "telegram_user_id": material.telegram_user_id,
            "telegram_chat_id": material.telegram_chat_id,
            "telegram_message_id": material.telegram_message_id,
            "message_date": datetime.fromtimestamp(material.message_date, UTC).isoformat(),
            "material_type": material.material_type.value,
        }
        if material.text is not None:
            data["text"] = material.text
        if material.caption is not None:
            data["caption"] = material.caption
        if material.source is not None:
            data["source"] = json.dumps(material.source.to_payload(), ensure_ascii=False)
        if material.attachment is not None:
            data["filename"] = material.attachment.filename
            if material.attachment.mime_type is not None:
                data["mime_type"] = material.attachment.mime_type

        files = None
        if material.attachment is not None and material.attachment.data is not None:
            files = {
                "file": (
                    material.attachment.filename,
                    material.attachment.data,
                    material.attachment.mime_type,
                )
            }

        response = await self.client.post(
            f"{self.base_url}/integrations/telegram/ingest",
            headers=self._headers(),
            data=data,
            files=files,
        )
        response.raise_for_status()
        return dict(response.json())

    async def set_mode(self, *, telegram_user_id: str, mode: str) -> None:
        response = await self.client.post(
            f"{self.base_url}/integrations/telegram/mode",
            headers=self._headers(),
            json={"telegram_user_id": telegram_user_id, "mode": mode},
        )
        response.raise_for_status()

    async def finish_collection(self, *, telegram_user_id: str) -> None:
        response = await self.client.post(
            f"{self.base_url}/integrations/telegram/finish",
            headers=self._headers(),
            json={"telegram_user_id": telegram_user_id},
        )
        response.raise_for_status()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.internal_token}"}
