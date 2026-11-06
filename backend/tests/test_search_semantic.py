import pytest

from app.modules.search.retrieval import ChunkHit
from app.modules.search.service import (
    SearchService,
    SearchValidationError,
    _fuse_chunks,
    _fuse_notes,
    _normalize_query,
    _Ranked,
)
from app.modules.search.terms import (
    ParsedQuery,
    highlight_ranges,
    highlight_terms,
    light_stem,
    metadata_score,
    metadata_term_groups,
)


def _hit(note: str, chunk: str, index: int = 0, score: float = 0.5) -> ChunkHit:
    return ChunkHit(
        source="content",
        source_type="content_object",
        source_id=note,
        chunk_id=chunk,
        chunk_index=index,
        text=f"python notes {chunk}",
        score=score,
    )


def test_tsquery_building() -> None:
    parsed = ParsedQuery.parse("Игры  Python")
    assert parsed.strict_tsquery() == "'игры' & 'python':*"
    assert parsed.loose_tsquery() == "'игр':* | 'python':*"
    assert ParsedQuery.parse("pyth").loose_tsquery() is None  # same as strict
    assert ParsedQuery.parse('"exact phrase" -skip').websearch
    assert ParsedQuery.parse("it's; DROP TABLE x").strict_tsquery() == (
        "'it' & 's' & 'drop' & 'table' & 'x'"
    )
    assert ParsedQuery.parse("!!!").strict_tsquery() is None


def test_light_stem() -> None:
    assert light_stem("заметки") == "замет"
    assert light_stem("games") == "game"
    assert light_stem("running") == "runn"
    assert light_stem("go") == "go"


def test_metadata_score_matches_old_local_scoring_rules() -> None:
    groups = metadata_term_groups("new python")
    parts = [("Python tips", 8.0), ("dev", 10.0)]
    assert metadata_score("new python", groups, parts) == 8.0
    # Generic words alone never match when a specific term exists.
    assert metadata_score("new python", groups, [("new release", 8.0)]) == 0.0
    # All terms matched doubles; whole query hit triples the field weight.
    assert metadata_score("python tips", metadata_term_groups("python tips"), parts) == 96.0
    # Synonyms: игры <-> game
    assert metadata_score("игры", metadata_term_groups("игры"), [("Best games", 8.0)]) > 0


def test_highlight_ranges_do_not_overlap() -> None:
    terms = highlight_terms("python py")
    ranges = highlight_ranges("Python and py", terms)
    assert [(item.start, item.end) for item in ranges] == [(0, 6), (11, 13)]


def test_note_fusion_combines_retrievers_and_limits_matches() -> None:
    lists = [
        _Ranked(1.0, "fts", chunks=[_hit("a", "a1"), _hit("b", "b1"), _hit("a", "a2", 1)]),
        _Ranked(1.0, "metadata", notes=["b", "c"]),
        _Ranked(1.0, "vector", chunks=[_hit("b", "b1"), _hit("a", "a3", 2)]),
    ]
    fused = _fuse_notes(lists, "python", k=60, limit=10)
    assert list(fused) == ["b", "a", "c"]
    assert [match.chunk_id for match in fused["a"]][:1] == ["a1"]
    assert len(fused["a"]) == 2
    assert fused["c"] == []  # metadata-only match has no chunk snippet
    assert fused["b"][0].highlight_ranges[0].start == 0
    assert list(_fuse_notes(lists, "python", k=60, limit=1)) == ["b"]


def test_chunk_fusion_reports_component_scores() -> None:
    vector_hit = ChunkHit(
        source="content",
        source_type="content_object",
        source_id="a",
        chunk_id="a1",
        chunk_index=0,
        text="t",
        score=0.9,
        distance=0.1,
    )
    results = _fuse_chunks(
        [
            _Ranked(1.0, "fts", chunks=[_hit("a", "a1", score=0.3)]),
            _Ranked(1.0, "vector", chunks=[vector_hit]),
        ],
        k=60,
    )
    assert results[0].vector_rank == 1 and results[0].full_text_rank == 1
    assert results[0].distance == pytest.approx(0.1)
    assert results[0].chunk_external_id == "content_object:a:chunk:0"


def test_query_validation_and_mode_resolution() -> None:
    with pytest.raises(SearchValidationError):
        _normalize_query("   ")
    assert _normalize_query("  a   b ") == "a b"
    service = SearchService(session=None, use_ai=False)  # type: ignore[arg-type]
    assert service.resolve_mode("hybrid") == "full_text"
    assert service.resolve_mode("semantic") == "full_text"
