from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import urlparse

import httpx


class EmbeddingProvider(Protocol):
    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> list[list[float]]:
        raise NotImplementedError


class FakeEmbeddingProvider:
    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> list[list[float]]:
        return [_fake_vector(text=text, model=model, dimensions=dimensions) for text in texts]


class HttpEmbeddingProvider:
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

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> list[list[float]]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, object] = {
            "model": model,
            "input": list(texts),
            "dimensions": dimensions,
        }
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        body = response.json()
        data = body.get("data")
        if not isinstance(data, list):
            raise ValueError("Embedding response does not contain a data list.")
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors: list[list[float]] = []
        for item in ordered:
            embedding = item.get("embedding")
            if not isinstance(embedding, list):
                raise ValueError("Embedding response item does not contain an embedding list.")
            vector = [float(value) for value in embedding]
            if len(vector) != dimensions:
                raise ValueError(
                    f"Embedding response dimensions {len(vector)} do not match configured "
                    f"dimensions {dimensions}."
                )
            vectors.append(vector)
        if len(vectors) != len(texts):
            raise ValueError("Embedding response count does not match request count.")
        return vectors


class YandexEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _normalize_yandex_embedding_base_url(base_url)
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> list[list[float]]:
        headers = self._headers()
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            for text in texts:
                payload: dict[str, object] = {
                    "modelUri": model,
                    "text": text,
                }
                response = await client.post(
                    f"{self.base_url}/textEmbedding",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                vectors.append(self._embedding_from_response(response.json(), dimensions))
        return vectors

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        stripped = self.api_key.strip()
        if stripped.startswith(("Bearer ", "Api-Key ")):
            return {"Authorization": stripped}
        if stripped.startswith("t1."):
            return {"Authorization": f"Bearer {stripped}"}
        if urlparse(self.base_url).hostname == "ai.api.cloud.yandex.net":
            return {"Authorization": f"Bearer {stripped}"}
        return {"Authorization": f"Api-Key {stripped}"}

    @staticmethod
    def _embedding_from_response(body: object, dimensions: int) -> list[float]:
        if not isinstance(body, dict):
            raise ValueError("Yandex embedding response is not an object.")
        embedding = body.get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("Yandex embedding response does not contain an embedding list.")
        vector = [float(value) for value in embedding]
        if dimensions > 0 and len(vector) != dimensions:
            raise ValueError(
                f"Embedding response dimensions {len(vector)} do not match configured "
                f"dimensions {dimensions}."
            )
        return vector


def build_embedding_provider(
    *,
    provider_name: str,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: int,
) -> EmbeddingProvider:
    if provider_name == "fake":
        return FakeEmbeddingProvider()
    if provider_name == "http":
        if not base_url:
            raise ValueError("VECTOR_EMBEDDING_BASE_URL is required for http embeddings.")
        return HttpEmbeddingProvider(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    if provider_name == "ollama":
        return HttpEmbeddingProvider(
            base_url=base_url or "http://127.0.0.1:11434/v1",
            api_key=None,
            timeout_seconds=timeout_seconds,
        )
    if provider_name == "yandex":
        return YandexEmbeddingProvider(
            base_url=base_url or "https://ai.api.cloud.yandex.net/foundationModels/v1",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported vector embedding provider: {provider_name}.")


def _fake_vector(*, text: str, model: str, dimensions: int) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{model}\0{text}\0{counter}".encode()).digest()
        for index in range(0, len(digest), 4):
            if len(values) >= dimensions:
                break
            chunk = digest[index : index + 4]
            integer = int.from_bytes(chunk, byteorder="big", signed=False)
            values.append((integer / 2**32) * 2 - 1)
        counter += 1
    return values


def _normalize_yandex_embedding_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.hostname in {"ai.api.cloud.yandex.net", "llm.api.cloud.yandex.net"}
        and parsed.path == "/v1"
    ):
        return normalized.removesuffix("/v1") + "/foundationModels/v1"
    return normalized
