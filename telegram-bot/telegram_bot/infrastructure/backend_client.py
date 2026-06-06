from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import httpx

from telegram_bot.domain.models import InboundMaterial, UserContext

logger = logging.getLogger(__name__)


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

    async def status(self, *, telegram_user_id: str) -> UserContext:
        logger.debug("Requesting Telegram link status telegram_user_id=%s", telegram_user_id)
        response = await self.client.get(
            f"{self.base_url}/integrations/telegram/status",
            headers=self._headers(),
            params={"telegram_user_id": telegram_user_id},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            logger.warning(
                "Unexpected Telegram status response telegram_user_id=%s payload_type=%s",
                telegram_user_id,
                type(payload).__name__,
            )
            return UserContext(telegram_user_id=telegram_user_id, linked=False)
        context = UserContext(
            telegram_user_id=telegram_user_id,
            linked=bool(payload.get("linked")),
            user_id=_string_or_none(payload.get("user_id")),
            display_name=_string_or_none(payload.get("display_name")),
        )
        logger.debug(
            "Telegram link status loaded telegram_user_id=%s linked=%s user_id=%s",
            telegram_user_id,
            context.linked,
            context.user_id,
        )
        return context

    async def ingest(
        self,
        material: InboundMaterial,
        *,
        target_collection_id: str | None = None,
    ) -> dict[str, object]:
        logger.info(
            "Sending Telegram material to backend user=%s chat=%s message=%s type=%s target=%s",
            material.telegram_user_id,
            material.telegram_chat_id,
            material.telegram_message_id,
            material.material_type.value,
            target_collection_id,
        )
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
        if target_collection_id is not None:
            data["target_collection_id"] = target_collection_id

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
        payload = dict(response.json())
        logger.info(
            "Telegram material backend response user=%s chat=%s message=%s status=%s",
            material.telegram_user_id,
            material.telegram_chat_id,
            material.telegram_message_id,
            payload.get("status"),
        )
        return payload

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.internal_token}"}


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
