from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

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


def build_structured_llm_generator() -> StructuredLLMGenerator:
    return UnavailableStructuredLLMGenerator()
