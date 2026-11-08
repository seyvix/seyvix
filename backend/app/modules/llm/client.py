"""The single AI client: any OpenAI-compatible API (chat, vision, embeddings, transcription).

AI is optional. `get_ai_client(settings)` returns None when `settings.ai_enabled` is False and
callers must degrade gracefully (FTS-only search, skipped enrichment).

Error model:
- `AIUnavailableError` — AI disabled, provider unreachable/overloaded after retries, or
  rejecting our credentials. Transient from a job's point of view: retry the job later.
- `AIResponseError` — the provider answered but the answer is unusable (invalid JSON after
  the repair retry, wrong embedding size, rejected request). Retrying the same input rarely
  helps; jobs should fail with a bounded number of attempts.
Both derive from `AIError`, so `except AIError` covers every AI failure.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
UNAVAILABLE_STATUS_CODES = frozenset({401, 402, 403, 404})
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 30.0
RETRY_AFTER_MAX_SECONDS = 120.0
_SCHEMA_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class AIError(Exception):
    """Base class of every AI client failure."""


class AIUnavailableError(AIError):
    """AI disabled or provider down/overloaded after retries (retryable for jobs)."""


class AIResponseError(AIError):
    """The provider answered, but the request was rejected or the answer is unusable."""


class AIClient:
    """Process-wide client. Safe for concurrent use; never construct one per request."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not settings.ai_api_key:
            raise AIUnavailableError("AI is disabled: AI_API_KEY is not set.")
        self.settings = settings
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(settings.ai_max_concurrency)
        # Some OpenAI-compatible servers reject `json_schema`; remember after the first refusal.
        self._json_schema_supported = True
        limits = httpx.Limits(
            max_connections=settings.ai_max_concurrency * 2,
            max_keepalive_connections=settings.ai_max_concurrency,
            keepalive_expiry=60.0,
        )
        endpoints = {
            "chat": (settings.ai_base_url, settings.ai_api_key),
            "embedding": (settings.ai_embedding_base_url, settings.ai_embedding_api_key),
            "vision": (settings.ai_vision_base_url, settings.ai_vision_api_key),
            "transcription": (
                settings.ai_transcription_base_url,
                settings.ai_transcription_api_key,
            ),
        }
        # One pooled HTTP client per distinct (base_url, key); capabilities share when equal.
        shared: dict[tuple[str, str], httpx.AsyncClient] = {}
        self._clients: dict[str, httpx.AsyncClient] = {}
        for capability, (base_url, api_key) in endpoints.items():
            key = (
                (base_url or settings.ai_base_url).rstrip("/") + "/",
                api_key or settings.ai_api_key,
            )
            if key not in shared:
                shared[key] = httpx.AsyncClient(
                    base_url=key[0],
                    headers={"Authorization": _authorization_header(key[1])},
                    timeout=httpx.Timeout(settings.ai_timeout_seconds, connect=10.0),
                    limits=limits,
                    transport=transport,
                )
            self._clients[capability] = shared[key]

    # --- public API ----------------------------------------------------------------------
    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        schema: type[TModel],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> TModel:
        """Chat completion validated into `schema`, with one repair round on invalid output."""
        model_name = model or self.settings.ai_chat_model
        json_schema = schema.model_json_schema()
        conversation = list(messages)
        content = await self._structured_completion(
            conversation, schema, json_schema, model_name, temperature, max_tokens
        )
        try:
            return _validate_json(content, schema)
        except AIResponseError as first_error:
            logger.warning(
                "ai.chat_json.repair",
                model=model_name,
                schema=schema.__name__,
                error=str(first_error)[:500],
            )
            conversation.extend(
                [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not valid for the required JSON schema: "
                            f"{str(first_error)[:1000]}\nReply again with only the corrected "
                            "JSON object, no prose and no code fences."
                        ),
                    },
                ]
            )
        repaired = await self._structured_completion(
            conversation, schema, json_schema, model_name, temperature, max_tokens
        )
        return _validate_json(repaired, schema)

    async def chat_text(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        capability: str = "chat",
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.settings.ai_chat_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        body = await self._post_json(
            "chat/completions", payload, operation="chat_text", capability=capability
        )
        return _message_content(body)

    async def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        """Embed `texts` in batches of `ai_embedding_batch_size`; order is preserved.
        `query=True` marks search queries (uses `ai_embedding_query_model` when configured)."""
        settings = self.settings
        model = self.embedding_model(query=query)
        vectors: list[list[float]] = []
        batch_size = settings.ai_embedding_batch_size
        for start in range(0, len(texts), batch_size):
            # OpenAI rejects empty strings in `input`.
            batch = [text if text.strip() else " " for text in texts[start : start + batch_size]]
            payload: dict[str, Any] = {
                "model": model,
                "input": batch,
                "encoding_format": "float",
            }
            if settings.ai_embedding_send_dimensions:
                payload["dimensions"] = settings.ai_embedding_dimensions
            task = (
                settings.ai_embedding_query_task
                if query and settings.ai_embedding_query_task
                else settings.ai_embedding_task
            )
            if task:
                payload["task"] = task
            body = await self._post_json(
                "embeddings", payload, operation="embed", capability="embedding"
            )
            vectors.extend(
                _embedding_vectors(
                    body, expected=len(batch), dimensions=settings.ai_embedding_dimensions
                )
            )
        return vectors

    def embedding_model(self, *, query: bool = False) -> str:
        if query and self.settings.ai_embedding_query_model:
            return self.settings.ai_embedding_query_model
        return self.settings.ai_embedding_model

    async def describe_image(
        self, image: bytes, mime_type: str, prompt: str, *, model: str | None = None
    ) -> str:
        encoded = base64.b64encode(image).decode("ascii")
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    },
                ],
            }
        ]
        return await self.chat_text(
            messages,
            model=model or self.settings.ai_vision_model,
            temperature=0.0,
            capability="vision",
        )

    async def transcribe(self, audio_path: Path, *, language: str | None = None) -> str:
        audio = await asyncio.to_thread(audio_path.read_bytes)
        data: dict[str, str] = {
            "model": self.settings.ai_transcription_model,
            "response_format": "json",
        }
        if language:
            data["language"] = language
        body = await self._request(
            "audio/transcriptions",
            operation="transcribe",
            model=self.settings.ai_transcription_model,
            capability="transcription",
            data=data,
            files={"file": (audio_path.name, audio, "application/octet-stream")},
        )
        text = body.get("text")
        if not isinstance(text, str):
            raise AIResponseError("Transcription response does not contain text.")
        return text.strip()

    async def aclose(self) -> None:
        for client in {id(c): c for c in self._clients.values()}.values():
            await client.aclose()

    # --- structured output ---------------------------------------------------------------
    async def _structured_completion(
        self,
        messages: list[dict[str, Any]],
        schema: type[BaseModel],
        json_schema: dict[str, Any],
        model: str,
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if self._json_schema_supported:
            payload["messages"] = messages
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _SCHEMA_NAME_RE.sub("_", schema.__name__)[:64] or "result",
                    "schema": json_schema,
                    "strict": False,
                },
            }
            try:
                body = await self._post_json("chat/completions", payload, operation="chat_json")
                return _message_content(body)
            except _RejectedRequestError as exc:
                logger.warning(
                    "ai.json_schema.rejected",
                    model=model,
                    status=exc.status_code,
                    error=exc.detail[:500],
                )
                # Only stop trying json_schema when the refusal is clearly about it.
                if _mentions_response_format(exc.detail):
                    self._json_schema_supported = False
        # Fallback: plain JSON mode with the schema spelled out in the prompt.
        payload["messages"] = [
            {
                "role": "system",
                "content": (
                    "Reply with a single JSON object that validates against this JSON schema. "
                    "No prose, no markdown, no code fences.\nJSON schema:\n"
                    + json.dumps(json_schema, ensure_ascii=False, separators=(",", ":"))
                ),
            },
            *messages,
        ]
        payload["response_format"] = {"type": "json_object"}
        try:
            body = await self._post_json("chat/completions", payload, operation="chat_json")
        except _RejectedRequestError as exc:
            raise AIResponseError(
                f"AI provider rejected the request ({exc.status_code}): {exc.detail[:500]}"
            ) from exc
        return _message_content(body)

    # --- transport -----------------------------------------------------------------------
    async def _post_json(
        self, path: str, payload: dict[str, Any], *, operation: str, capability: str = "chat"
    ) -> dict[str, Any]:
        try:
            return await self._request(
                path,
                operation=operation,
                model=str(payload.get("model")),
                capability=capability,
                json_body=payload,
            )
        except _RejectedRequestError as exc:
            if operation == "chat_json":
                raise  # handled by the json_schema fallback
            raise AIResponseError(
                f"AI provider rejected the request ({exc.status_code}): {exc.detail[:500]}"
            ) from exc

    async def _request(
        self,
        path: str,
        *,
        operation: str,
        model: str,
        capability: str = "chat",
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        max_retries = self.settings.ai_max_retries
        attempt = 0
        while True:
            started = time.monotonic()
            retry_after: float | None = None
            try:
                async with self._semaphore:
                    response = await self._clients[capability].post(
                        path, json=json_body, data=data, files=files
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                failure = f"{type(exc).__name__}: {exc}"
            else:
                status = response.status_code
                if status < 400:
                    body = _decode_body(response)
                    _log_usage(operation, model, body, time.monotonic() - started, attempt)
                    return body
                detail = response.text[:1000]
                if status in UNAVAILABLE_STATUS_CODES:
                    raise AIUnavailableError(
                        f"AI provider refused {operation} ({status}): {detail[:300]}"
                    )
                if status not in RETRYABLE_STATUS_CODES:
                    raise _RejectedRequestError(status, detail)
                failure = f"HTTP {status}: {detail[:300]}"
                retry_after = _retry_after_seconds(response.headers.get("retry-after"))
            if attempt >= max_retries:
                logger.warning(
                    "ai.request.gave_up",
                    operation=operation,
                    model=model,
                    attempts=attempt + 1,
                    error=failure,
                )
                raise AIUnavailableError(
                    f"AI provider unavailable for {operation} after {attempt + 1} attempts: "
                    f"{failure}"
                )
            delay = _backoff_delay(attempt, retry_after)
            logger.info(
                "ai.request.retry",
                operation=operation,
                model=model,
                attempt=attempt + 1,
                retry_in_seconds=round(delay, 2),
                error=failure,
            )
            attempt += 1
            await self._sleep(delay)


class _RejectedRequestError(Exception):
    """Non-retryable 4xx (bad request, unsupported parameter)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


# --- helpers -----------------------------------------------------------------------------
def _authorization_header(api_key: str) -> str:
    stripped = api_key.strip()
    if stripped.startswith(("Bearer ", "Api-Key ")):
        return stripped
    return f"Bearer {stripped}"


def _mentions_response_format(detail: str) -> bool:
    lowered = detail.casefold()
    return any(marker in lowered for marker in ("response_format", "json_schema", "schema"))


def _backoff_delay(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, RETRY_AFTER_MAX_SECONDS) + random.uniform(0, 0.5)
    ceiling = min(BACKOFF_BASE_SECONDS * 2**attempt, BACKOFF_MAX_SECONDS)
    # "Equal jitter": at least half the exponential delay, spread over the other half.
    return float(ceiling / 2 + random.uniform(0, ceiling / 2))


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max((moment - datetime.now(UTC)).total_seconds(), 0.0)


def _decode_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise AIResponseError("AI provider returned a non-JSON response.") from exc
    if not isinstance(body, dict):
        raise AIResponseError("AI provider returned an unexpected JSON payload.")
    return body


def _message_content(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AIResponseError("AI chat response does not contain choices.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AIResponseError("AI chat response message is invalid.")
    content = message.get("content")
    if isinstance(content, list):  # some servers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        refusal = message.get("refusal")
        raise AIResponseError(f"AI chat response has no content (refusal: {refusal!r}).")
    return content


def _validate_json[M: BaseModel](content: str, schema: type[M]) -> M:
    stripped = content.strip()
    fenced = _JSON_FENCE_RE.match(stripped)
    if fenced:
        stripped = fenced.group(1)
    # Reasoning models sometimes prepend a <think> block; keep the outermost object only.
    if not stripped.startswith("{"):
        start, end = stripped.find("{"), stripped.rfind("}")
        if start != -1 and end > start:
            stripped = stripped[start : end + 1]
    try:
        return schema.model_validate_json(stripped)
    except ValidationError as exc:
        raise AIResponseError(
            f"invalid JSON for {schema.__name__}: {exc.errors(include_url=False)}"
        ) from exc


def _embedding_vectors(
    body: dict[str, Any], *, expected: int, dimensions: int
) -> list[list[float]]:
    data = body.get("data")
    if not isinstance(data, list) or len(data) != expected:
        raise AIResponseError("Embedding response size does not match the request.")
    items = sorted(data, key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0)
    vectors: list[list[float]] = []
    for item in items:
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(embedding, list):
            raise AIResponseError("Embedding response item is invalid.")
        if len(embedding) != dimensions:
            raise AIResponseError(
                f"Embedding has {len(embedding)} dimensions, expected {dimensions} "
                "(check AI_EMBEDDING_MODEL / AI_EMBEDDING_DIMENSIONS)."
            )
        vectors.append([float(value) for value in embedding])
    return vectors


def _log_usage(
    operation: str, model: str, body: dict[str, Any], seconds: float, retries: int
) -> None:
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    logger.info(
        "ai.usage",
        operation=operation,
        model=body.get("model") or model,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        duration_ms=round(seconds * 1000),
        retries=retries,
    )


# --- process-wide singleton --------------------------------------------------------------
_client: AIClient | None = None
_client_settings: Settings | None = None


def get_ai_client(settings: Settings) -> AIClient | None:
    """The process-wide client, or None when AI is disabled (`AI_API_KEY` unset)."""
    global _client, _client_settings
    if not settings.ai_enabled:
        return None
    if _client is None or _client_settings is not settings:
        _client = AIClient(settings)
        _client_settings = settings
    return _client


async def close_ai_client() -> None:
    """Close the singleton (API lifespan shutdown / worker shutdown)."""
    global _client, _client_settings
    client, _client, _client_settings = _client, None, None
    if client is not None:
        await client.aclose()
