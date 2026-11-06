from __future__ import annotations

import logging
from base64 import b64encode
from collections import OrderedDict
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Sticker

from telegram_bot.domain.models import InboundMaterial
from telegram_bot.services.ingest import FileTooLargeError

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 300
MAX_EMOJI_PREVIEW_BYTES = 64 * 1024
EMOJI_CACHE_SIZE = 512


class TelegramFileFetcher:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._emoji_cache: OrderedDict[str, dict[str, Any] | None] = OrderedDict()

    async def download(self, file_id: str, destination: Path) -> None:
        """Stream a Telegram file to disk (aiogram writes it in chunks)."""
        try:
            await self.bot.download(
                file_id,
                destination=destination,
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
        except TelegramBadRequest as exc:
            # The Bot API has no dedicated error type for the 20 MB getFile limit.
            if "too big" in exc.message.casefold():
                raise FileTooLargeError(file_id) from exc
            raise

    async def enrich(self, material: InboundMaterial) -> InboundMaterial:
        """Attach small previews of custom emoji so the web can render them."""
        source = material.source
        if source is None or not source.custom_emoji_ids:
            return material
        assets = await self._emoji_assets(list(dict.fromkeys(source.custom_emoji_ids)))
        if not assets:
            return material
        metadata = dict(source.metadata or {})
        metadata["custom_emoji_assets"] = assets
        return replace(material, source=source.with_metadata(metadata))

    async def _emoji_assets(self, emoji_ids: list[str]) -> dict[str, dict[str, Any]]:
        missing = [emoji_id for emoji_id in emoji_ids if emoji_id not in self._emoji_cache]
        if missing:
            try:
                stickers = await self.bot.get_custom_emoji_stickers(custom_emoji_ids=missing[:200])
            except TelegramAPIError:
                logger.warning("Could not load custom emoji stickers", exc_info=True)
                stickers = []
            found = {sticker.custom_emoji_id: sticker for sticker in stickers}
            for emoji_id in missing:
                sticker = found.get(emoji_id)
                self._remember(emoji_id, await self._preview(sticker) if sticker else None)
        assets: dict[str, dict[str, Any]] = {}
        for emoji_id in emoji_ids:
            asset = self._emoji_cache.get(emoji_id)
            if asset is not None:
                assets[emoji_id] = asset
        return assets

    async def _preview(self, sticker: Sticker) -> dict[str, Any] | None:
        preview = sticker.thumbnail
        if preview is None or (preview.file_size or 0) > MAX_EMOJI_PREVIEW_BYTES:
            return None
        buffer = BytesIO()
        try:
            await self.bot.download(preview.file_id, destination=buffer)
        except TelegramAPIError:
            logger.warning("Could not download custom emoji preview", exc_info=True)
            return None
        data = buffer.getvalue()
        if len(data) > MAX_EMOJI_PREVIEW_BYTES:
            return None
        return {
            "data_url": f"data:image/webp;base64,{b64encode(data).decode()}",
            "fallback": sticker.emoji,
        }

    def _remember(self, emoji_id: str, asset: dict[str, Any] | None) -> None:
        self._emoji_cache[emoji_id] = asset
        self._emoji_cache.move_to_end(emoji_id)
        while len(self._emoji_cache) > EMOJI_CACHE_SIZE:
            self._emoji_cache.popitem(last=False)
