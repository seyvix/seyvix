from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChunkingLimits:
    max_document_chars: int
    max_chunks_per_document: int
    max_tokens_per_chunk: int
    overlap_tokens: int
    config_version: str


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_index: int
    chunk_external_id: str
    text: str
    text_hash: str
    token_count: int
    metadata: dict[str, Any]


def stable_json_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def approximate_token_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return len(stripped.split())


def chunk_text(
    text: str,
    *,
    document_external_id: str,
    strategy: str,
    metadata: dict[str, Any],
    limits: ChunkingLimits,
) -> list[TextChunk]:
    normalized = text.strip()
    if not normalized:
        raise ValueError("Vectorization document text is empty.")
    if len(text) > limits.max_document_chars:
        raise ValueError(
            f"Vectorization document exceeds maximum size of {limits.max_document_chars} chars."
        )
    if limits.overlap_tokens >= limits.max_tokens_per_chunk:
        raise ValueError("Vector chunk overlap must be lower than max tokens per chunk.")
    if strategy not in {
        "short_document",
        "default",
        "content_text",
        "snapshot_text",
        "metadata_only",
    }:
        raise ValueError(f"Unsupported chunking strategy: {strategy}.")

    tokens = normalized.split()
    if strategy == "short_document" and len(tokens) <= limits.max_tokens_per_chunk:
        return [_build_chunk(0, document_external_id, normalized, metadata)]

    step = limits.max_tokens_per_chunk - limits.overlap_tokens
    chunks: list[TextChunk] = []
    for start in range(0, len(tokens), step):
        chunk_tokens = tokens[start : start + limits.max_tokens_per_chunk]
        if not chunk_tokens:
            break
        chunks.append(
            _build_chunk(len(chunks), document_external_id, " ".join(chunk_tokens), metadata)
        )
        if start + limits.max_tokens_per_chunk >= len(tokens):
            break
        if len(chunks) >= limits.max_chunks_per_document:
            raise ValueError(
                f"Vectorization document exceeds maximum chunk count of "
                f"{limits.max_chunks_per_document}."
            )
    return chunks


def _build_chunk(
    chunk_index: int,
    document_external_id: str,
    text: str,
    metadata: dict[str, Any],
) -> TextChunk:
    return TextChunk(
        chunk_index=chunk_index,
        chunk_external_id=f"{document_external_id}:chunk:{chunk_index}",
        text=text,
        text_hash=stable_json_hash(text),
        token_count=approximate_token_count(text),
        metadata=dict(metadata),
    )
