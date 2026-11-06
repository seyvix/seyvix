"""AI-backed enrichment (OCR, image/video description, transcription) via the shared client.

Each capability is available only when AI is configured AND its feature flag is on. When a
capability is off, callers skip it and the snapshot still completes. `AIUnavailableError`
(provider down after the client's own retries) propagates so the job is retried later;
`AIResponseError` (a rejected request / unusable output) only degrades the result.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.core.config import Settings
from app.modules.llm.client import AIClient, get_ai_client

OCR_PROMPT: Final = (
    "Extract all readable text from this image. Preserve line breaks and table-like "
    "structure where possible. Return only the extracted text, or nothing if there is none."
)
DESCRIBE_PROMPT: Final = (
    "Describe this image for later semantic search. Include visible objects, people, UI, "
    "diagrams, text, context, and any searchable domain terms."
)


@dataclass(frozen=True, slots=True)
class AIEnrichment:
    client: AIClient | None
    ocr_enabled: bool
    vision_enabled: bool
    transcription_enabled: bool
    vision_model: str

    @classmethod
    def from_settings(cls, settings: Settings) -> AIEnrichment:
        client = get_ai_client(settings)
        return cls(
            client=client,
            ocr_enabled=client is not None and settings.ai_ocr_enabled,
            vision_enabled=client is not None and settings.ai_vision_enabled,
            transcription_enabled=client is not None and settings.ai_transcription_enabled,
            vision_model=settings.ai_vision_model,
        )

    def _client(self) -> AIClient:
        if self.client is None:  # guarded by the *_enabled flags
            raise RuntimeError("AI client is not configured")
        return self.client

    async def ocr(self, image: bytes, mime_type: str) -> str:
        return await self._client().describe_image(image, mime_type, OCR_PROMPT)

    async def describe_image(self, image: bytes, mime_type: str) -> str:
        return await self._client().describe_image(image, mime_type, DESCRIBE_PROMPT)

    async def describe_frames(self, frames: list[bytes], *, start: int, end: int) -> str:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Describe this video segment for later semantic search. These frames are "
                    f"sampled from {start}-{end} seconds. Mention visible objects, UI, actions, "
                    "slides, scenes, and readable text."
                ),
            }
        ]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(frame).decode()},
            }
            for frame in frames
        )
        return await self._client().chat_text(
            [{"role": "user", "content": content}], model=self.vision_model, temperature=0.0
        )

    async def transcribe(self, audio: Path) -> str:
        return await self._client().transcribe(audio)
