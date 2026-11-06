from app.core.config import Settings
from app.modules.vectorization.chunking import (
    ChunkingConfig,
    chunk_text,
    content_hash,
    text_hash,
)
from app.modules.vectorization.documents import is_supported_source
from app.modules.vectorization.models import VectorizationChunk


def _config(**overrides: int) -> ChunkingConfig:
    values = {
        "max_tokens": 16,
        "overlap_tokens": 4,
        "max_chunks": 200,
        "max_document_chars": 100_000,
    }
    values.update(overrides)
    return ChunkingConfig(version="test", **values)


def test_short_text_is_one_chunk_preserving_newlines() -> None:
    chunks = chunk_text("Title\n\nfirst line\nsecond line", _config())
    assert len(chunks) == 1
    assert chunks[0].text == "Title\n\nfirst line\nsecond line"
    assert chunks[0].token_count == 5
    assert chunks[0].text_hash == text_hash(chunks[0].text)


def test_long_text_uses_overlapping_windows() -> None:
    words = [f"w{index}" for index in range(40)]
    chunks = chunk_text(" ".join(words), _config())
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].text.split() == words[:16]
    assert chunks[1].text.split()[:4] == words[12:16]  # 4-token overlap
    assert chunks[-1].text.split()[-1] == words[-1]


def test_limits_truncate_instead_of_failing() -> None:
    text = " ".join(f"w{index}" for index in range(1000))
    assert len(chunk_text(text, _config(max_chunks=3))) == 3
    assert chunk_text("", _config()) == []
    # A space-free blob is split so no chunk exceeds the character budget.
    blob = chunk_text("x" * 10_000, _config())
    assert all(len(chunk.text) <= 16 * 8 for chunk in blob)


def test_unchanged_text_keeps_hash_and_config_changes_it() -> None:
    assert content_hash("abc", _config()) == content_hash("abc", _config())
    assert content_hash("abc", _config()) != content_hash("abd", _config())
    assert content_hash("abc", _config()) != content_hash("abc", _config(max_tokens=32))


def test_appending_text_keeps_leading_chunk_hashes() -> None:
    base = " ".join(f"w{index}" for index in range(40))
    before = chunk_text(base, _config())
    after = chunk_text(base + " extra words at the end", _config())
    assert before[0].text_hash == after[0].text_hash  # embedding reused, not recomputed


def test_config_from_settings_clamps_overlap() -> None:
    config = ChunkingConfig.from_settings(
        Settings(vector_chunk_max_tokens=100, vector_chunk_overlap_tokens=90)
    )
    assert config.overlap_tokens == 50


def test_supported_sources_and_schema() -> None:
    assert is_supported_source("content", "content_object")
    assert is_supported_source("taxonomy", "category_profile")
    assert not is_supported_source("content", "unknown")
    columns = VectorizationChunk.__table__.c
    assert columns.search_vector.computed is not None
    assert "halfvec" in str(columns.embedding.type).lower()
    index_names = {index.name for index in VectorizationChunk.__table__.indexes}
    assert "ix_vectorization_chunks_embedding_hnsw" in index_names
    assert "ix_vectorization_chunks_search_vector" in index_names
