"""Mini test suite for merge_context: dedup, score-based ranking, and token-budget trimming."""

from src.pipeline.merge import merge_context
from src.schemas import Citation


def _citation(id: str, score: float | None, snippet_len: int = 10) -> Citation:
    return Citation(id=id, source_type="vector", title="t", snippet="x" * snippet_len, score=score)


def test_dedupes_by_id_across_retrievers() -> None:
    a = _citation("1", score=0.9)
    b = _citation("1", score=0.9)
    c = _citation("2", score=0.5)
    merged = merge_context([[a], [b, c]])
    assert [c.id for c in merged] == ["1", "2"]


def test_ranks_by_score_descending() -> None:
    low = _citation("low", score=0.1)
    high = _citation("high", score=0.9)
    merged = merge_context([[low, high]])
    assert [c.id for c in merged] == ["high", "low"]


def test_unscored_citations_sort_last() -> None:
    scored = _citation("scored", score=0.1)
    unscored = _citation("unscored", score=None)
    merged = merge_context([[unscored, scored]])
    assert [c.id for c in merged] == ["scored", "unscored"]


def test_trims_to_token_budget() -> None:
    kept = _citation("kept", score=0.9, snippet_len=400)
    dropped = _citation("dropped", score=0.1, snippet_len=400)
    merged = merge_context([[kept, dropped]], max_tokens=100)
    assert [c.id for c in merged] == ["kept"]


def test_always_keeps_at_least_one_citation_even_over_budget() -> None:
    oversized = _citation("oversized", score=0.9, snippet_len=1000)
    merged = merge_context([[oversized]], max_tokens=1)
    assert [c.id for c in merged] == ["oversized"]


def test_fills_remaining_budget_with_smaller_lower_score_items() -> None:
    big = _citation("big", score=0.9, snippet_len=400)
    small = _citation("small", score=0.5, snippet_len=20)
    merged = merge_context([[big, small]], max_tokens=105)
    assert {c.id for c in merged} == {"big", "small"}
