import json

import httpx
import pytest

from app.modules.llm.contracts import (
    HttpStructuredLLMGenerator,
    LLMGenerationError,
    UnavailableStructuredLLMGenerator,
    build_structured_llm_generator,
)


@pytest.mark.asyncio
async def test_ollama_structured_generator_uses_openai_compatible_chat_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3:4b-thinking"
        assert payload["temperature"] == 0
        assert payload["response_format"] == {"type": "json_object"}
        assert "selected_category_id" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "selected_category_id": "category-id",
                                    "confidence": 0.86,
                                    "should_assign": True,
                                    "status": "accepted",
                                    "reasoning": "Best semantic candidate.",
                                    "alternatives": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    generator = build_structured_llm_generator(
        provider_name="ollama",
        base_url="http://ollama.local/v1",
        api_key="ignored",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )

    result = await generator.generate_structured(
        prompt="Choose from candidates.",
        schema={
            "type": "object",
            "properties": {"selected_category_id": {"type": ["string", "null"]}},
        },
        model_config={"model": "qwen3:4b-thinking", "temperature": 0},
    )

    assert result["selected_category_id"] == "category-id"
    assert result["confidence"] == 0.86


@pytest.mark.asyncio
async def test_http_structured_generator_adds_bearer_token_and_rejects_invalid_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    generator = HttpStructuredLLMGenerator(
        base_url="http://llm.local/v1",
        api_key="secret",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMGenerationError, match="valid JSON"):
        await generator.generate_structured(
            prompt="Return JSON.",
            schema={"type": "object"},
            model_config={"model": "model", "temperature": 0},
        )


@pytest.mark.asyncio
async def test_unavailable_structured_generator_fails_explicitly() -> None:
    with pytest.raises(LLMGenerationError, match="not configured"):
        await UnavailableStructuredLLMGenerator().generate_structured(
            prompt="Return JSON.",
            schema={"type": "object"},
            model_config={"model": "model"},
        )
