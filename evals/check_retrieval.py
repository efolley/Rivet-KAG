"""Mini retrieval-accuracy check against the *live* Milvus and Neo4j instances.

Unlike tests/test_retrieval.py (mocked, runs in CI), this hits the real databases loaded by
`make ingest`, so it proves the retrievers actually find the right thing in the sample data,
not just that the mapping code is correct. It's a hand-rolled precursor to the DeepEval suite
planned for Phase 4 (see the roadmap) — same idea, 10 questions instead of 25, no framework.

Usage:
  make eval
  uv run python -m evals.check_retrieval
"""

import asyncio
import json
import sys
from pathlib import Path

from src.pipeline.retrieval.milvus import MilvusRetriever
from src.pipeline.retrieval.neo4j import Neo4jRetriever
from src.schemas import Citation

QUESTIONS_PATH = Path(__file__).parent / "golden_questions.json"


def _check_vector(question: dict[str, object], citations: list[Citation]) -> tuple[bool, str]:
    expected = question["vector_source"]
    top = citations[0].title if citations else None
    hit = bool(citations) and any(c.title.startswith(str(expected)) for c in citations[:1])
    return hit, f"expected top source {expected!r}, got {top!r}"


def _check_graph(question: dict[str, object], citations: list[Citation]) -> tuple[bool, str]:
    expected = question["graph_contains"]
    assert isinstance(expected, list)
    combined = " ".join(c.snippet for c in citations)
    missing = [name for name in expected if name not in combined]
    return not missing, f"expected {expected} in graph results, missing {missing}" if missing else "ok"


async def main() -> int:
    questions = json.loads(QUESTIONS_PATH.read_text())
    vector, graph = MilvusRetriever(), Neo4jRetriever()
    passed = 0

    for q in questions:
        question = str(q["question"])
        if "vector_source" in q:
            citations = await vector.retrieve(question)
            ok, detail = _check_vector(q, citations)
        else:
            citations = await graph.retrieve(question)
            ok, detail = _check_graph(q, citations)
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}\n       {detail}")

    total = len(questions)
    print(f"\n{passed}/{total} correct ({passed / total:.0%})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
