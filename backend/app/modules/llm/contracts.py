from __future__ import annotations

import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="llm",
    description="LLM provider abstraction, prompt execution, and model policy enforcement.",
    public_contracts=[
        "completion-request",
        "tool-call",
        "provider-policy",
        "structured-generation",
    ],
    plugin_capabilities=["llm_provider", "tool_runtime"],
)


class LLMGenerationError(Exception):
    pass


class LLMModelConfig(BaseModel):
    model: str = Field(min_length=1)
    temperature: float = Field(default=0, ge=0, le=2)


class StructuredLLMGenerator(Protocol):
    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class UnavailableStructuredLLMGenerator:
    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
    ) -> dict[str, Any]:
        _ = prompt, schema, model_config
        raise LLMGenerationError("Structured LLM generation provider is not configured.")


class HttpStructuredLLMGenerator:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": str(model_config["model"]),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON. The JSON must match the supplied schema. "
                        "Do not include hidden reasoning, prose, markdown, or code fences. "
                        "/no_think"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "JSON schema:\n"
                        f"{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
                    ),
                },
            ],
            "temperature": float(model_config.get("temperature", 0)),
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if model_config.get("max_tokens") is not None:
            payload["max_tokens"] = int(model_config["max_tokens"])
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMGenerationError("Structured LLM generation request failed.") from exc
        content = _extract_openai_compatible_message_content(response.json())
        return _parse_json_object(content)


class OllamaStructuredLLMGenerator(HttpStructuredLLMGenerator):
    def __init__(
        self,
        *,
        base_url: str | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=(base_url or "http://127.0.0.1:11434").removesuffix("/v1"),
            api_key=None,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": str(model_config["model"]),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON. The JSON must match the supplied schema. "
                        "Do not include hidden reasoning, prose, markdown, or code fences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "JSON schema:\n"
                        f"{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
                    ),
                },
            ],
            "format": "json",
            "stream": False,
            "think": False,
            "options": {"temperature": float(model_config.get("temperature", 0))},
        }
        if model_config.get("max_tokens") is not None:
            payload["options"]["num_predict"] = int(model_config["max_tokens"])
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMGenerationError("Structured LLM generation request failed.") from exc
        message = response.json().get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LLMGenerationError("Structured LLM response message content is invalid.")
        return _parse_json_object(message["content"])


def build_structured_llm_generator(
    *,
    provider_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> StructuredLLMGenerator:
    if provider_name is None:
        settings = get_settings()
        provider_name = settings.llm_structured_provider
        base_url = settings.llm_structured_base_url
        api_key = settings.llm_structured_api_key
        timeout_seconds = settings.llm_structured_timeout_seconds
    timeout = timeout_seconds or 120
    if provider_name == "disabled":
        return UnavailableStructuredLLMGenerator()
    if provider_name == "http":
        if not base_url:
            raise LLMGenerationError("LLM_STRUCTURED_BASE_URL is required for http provider.")
        return HttpStructuredLLMGenerator(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout,
            transport=transport,
        )
    if provider_name == "ollama":
        return OllamaStructuredLLMGenerator(
            base_url=base_url,
            timeout_seconds=timeout,
            transport=transport,
        )
    raise LLMGenerationError(f"Unsupported structured LLM provider: {provider_name}.")


def _extract_openai_compatible_message_content(response_body: dict[str, Any]) -> str:
    choices = response_body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMGenerationError("Structured LLM response does not contain choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise LLMGenerationError("Structured LLM response choice is invalid.")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise LLMGenerationError("Structured LLM response message is invalid.")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMGenerationError("Structured LLM response message content is invalid.")
    return content


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMGenerationError("Structured LLM response is not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMGenerationError("Structured LLM response JSON must be an object.")
    return parsed
