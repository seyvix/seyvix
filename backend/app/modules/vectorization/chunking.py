"""Overlapping token-window chunking that preserves the original text (incl. newlines)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.core.config import Settings

# Whitespace-separated "tokens", split further every 32 chars so a pathological run without
# spaces (base64, CJK) can never produce a chunk larger than the embedding model accepts.
_TOKEN_RE = re.compile(r"\S{1,32}")
# Upper bound on a chunk's character span relative to its token budget.
_MAX_CHARS_PER_TOKEN = 8


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    max_tokens: int
    overlap_tokens: int
    max_chunks: int
    max_document_chars: int
    version: str

    @classmethod
    def from_settings(cls, settings: Settings) -> ChunkingConfig:
        max_tokens = max(settings.vector_chunk_max_tokens, 16)
        return cls(
            max_tokens=max_tokens,
            overlap_tokens=min(max(settings.vector_chunk_overlap_tokens, 0), max_tokens // 2),
            max_chunks=max(settings.vector_chunk_max_chunks_per_document, 1),
            max_document_chars=max(settings.vector_chunk_max_document_chars, 1000),
            version=settings.vector_chunk_config_version,
        )

    @property
    def fingerprint(self) -> str:
        return (
            f"{self.version}:{self.max_tokens}:{self.overlap_tokens}:"
            f"{self.max_chunks}:{self.max_document_chars}"
        )


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    text: str
    text_hash: str
    token_count: int


def text_hash(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8"), digest_size=16).hexdigest()


def content_hash(text: str, config: ChunkingConfig) -> str:
    digest = hashlib.sha256(config.fingerprint.encode("utf-8"))
    digest.update(b"\0")
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def chunk_text(text: str, config: ChunkingConfig) -> list[TextChunk]:
    """Split `text` into overlapping windows; over-long documents are truncated, not rejected."""
    text = text[: config.max_document_chars]
    spans = [match.span() for match in _TOKEN_RE.finditer(text)]
    if not spans:
        return []
    max_chars = config.max_tokens * _MAX_CHARS_PER_TOKEN
    chunks: list[TextChunk] = []
    start = 0
    total = len(spans)
    while start < total and len(chunks) < config.max_chunks:
        first_char = spans[start][0]
        end = start + 1
        limit = min(start + config.max_tokens, total)
        while end < limit and spans[end][1] - first_char <= max_chars:
            end += 1
        piece = text[first_char : spans[end - 1][1]]
        chunks.append(
            TextChunk(
                index=len(chunks), text=piece, text_hash=text_hash(piece), token_count=end - start
            )
        )
        if end >= total:
            break
        start = max(end - config.overlap_tokens, start + 1)
    return chunks
