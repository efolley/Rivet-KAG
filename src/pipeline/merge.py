from src.schemas import Citation


def merge_context(results: list[list[Citation]]) -> list[Citation]:
    """Flatten retriever results, dropping duplicate ids. TODO: rerank."""
    seen: set[str] = set()
    merged: list[Citation] = []
    for citations in results:
        for c in citations:
            if c.id not in seen:
                seen.add(c.id)
                merged.append(c)
    return merged
