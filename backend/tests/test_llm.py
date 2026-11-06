import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.modules.llm.client import (
    AIClient,
    AIResponseError,
    AIUnavailableError,
    get_ai_client,
)


class Answer(BaseModel):
    label: str
    score: float


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ai_api_key": "test-key",
        "ai_base_url": "https://ai.test/v1",
        "ai_max_retries": 2,
        "ai_embedding_dimensions": 64,
        "ai_embedding_batch_size": 2,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _chat(content: str) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


async def _no_sleep(_: float) -> None:
    return None


def _client(handler, **overrides: object) -> AIClient:
    return AIClient(_settings(**overrides), transport=httpx.MockTransport(handler), sleep=_no_sleep)


def test_get_ai_client_is_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)
    assert get_ai_client(Settings(ai_api_key=None)) is None
    settings = _settings()
    assert get_ai_client(settings) is get_ai_client(settings)


@pytest.mark.asyncio
async def test_chat_json_uses_json_schema_and_validates() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=_chat('{"label": "x", "score": 0.5}'))

    client = _client(handler)
    answer = await client.chat_json([{"role": "user", "content": "hi"}], Answer)
    assert answer == Answer(label="x", score=0.5)
    assert seen[0]["response_format"]["type"] == "json_schema"  # type: ignore[index]
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_json_falls_back_to_json_object_and_repairs_once() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, text="response_format json_schema is not supported")
        if len(calls) == 2:
            return httpx.Response(200, json=_chat('{"label": "x"}'))  # missing score
        return httpx.Response(200, json=_chat('```json\n{"label": "y", "score": 1}\n```'))

    client = _client(handler)
    answer = await client.chat_json([{"role": "user", "content": "hi"}], Answer)
    assert answer == Answer(label="y", score=1)
    assert [call["response_format"]["type"] for call in calls] == [  # type: ignore[index]
        "json_schema",
        "json_object",
        "json_object",
    ]
    # The repair request carries the invalid answer back to the model.
    assert calls[2]["messages"][-2]["role"] == "assistant"  # type: ignore[index]
    # json_schema is remembered as unsupported for this client.
    await client.chat_json([{"role": "user", "content": "again"}], Answer)
    assert calls[-1]["response_format"]["type"] == "json_object"  # type: ignore[index]
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_json_raises_after_failed_repair() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat("not json"))

    client = _client(handler)
    with pytest.raises(AIResponseError):
        await client.chat_json([{"role": "user", "content": "hi"}], Answer)
    await client.aclose()


@pytest.mark.asyncio
async def test_retries_on_429_with_retry_after_then_gives_up() -> None:
    delays: list[float] = []
    attempts = 0

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")

    client = AIClient(_settings(), transport=httpx.MockTransport(handler), sleep=record_sleep)
    with pytest.raises(AIUnavailableError):
        await client.chat_text([{"role": "user", "content": "hi"}])
    assert attempts == 3  # first try + ai_max_retries
    assert all(7 <= delay < 8 for delay in delays)
    await client.aclose()


@pytest.mark.asyncio
async def test_retries_transport_errors_and_recovers() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=_chat("hello"))

    client = _client(handler)
    assert await client.chat_text([{"role": "user", "content": "hi"}]) == "hello"
    assert attempts == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_failure_is_unavailable_without_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, text="bad key")

    client = _client(handler)
    with pytest.raises(AIUnavailableError):
        await client.embed(["a"])
    assert attempts == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_embed_batches_preserves_order_and_checks_dimensions() -> None:
    batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        batches.append(body["input"])
        assert body["dimensions"] == 64
        data = [
            {"index": index, "embedding": [float(len(text))] * 64}
            for index, text in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"data": list(reversed(data))})

    client = _client(handler)
    vectors = await client.embed(["a", "bb", "ccc"])
    assert batches == [["a", "bb"], ["ccc"]]
    assert [vector[0] for vector in vectors] == [1.0, 2.0, 3.0]
    await client.aclose()

    def wrong_size(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 3}]})

    client = _client(wrong_size)
    with pytest.raises(AIResponseError):
        await client.embed(["a"])
    await client.aclose()
