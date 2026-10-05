from src.schemas import Citation

_CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS = 2000


def _estimate_tokens(c: Citation) -> int:
    return (len(c.title) + len(c.snippet)) // _CHARS_PER_TOKEN


def merge_context(
    results: list[list[Citation]], max_tokens: int = DEFAULT_MAX_TOKENS
) -> list[Citation]:
    """Dedupe by id, rank by score (unscored last), and trim to a token budget.

    Citations are cheap to estimate (title + snippet only, no LLM call) so this stays
    inside the $0.005 merge budget in the README's cost table.
    """
    seen: set[str] = set()
    deduped: list[Citation] = []
    for citations in results:
        for c in citations:
            if c.id not in seen:
                seen.add(c.id)
                deduped.append(c)

    ranked = sorted(deduped, key=lambda c: c.score if c.score is not None else float("-inf"), reverse=True)

    budget = max_tokens
    kept: list[Citation] = []
    for c in ranked:
        cost = _estimate_tokens(c)
        if kept and cost > budget:
            continue
        budget -= cost
        kept.append(c)
    return kept
