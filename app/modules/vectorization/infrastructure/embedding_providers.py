from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

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
