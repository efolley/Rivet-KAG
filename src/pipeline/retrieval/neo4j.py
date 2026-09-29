"""Real graph retriever: builds a Cypher query from the question's keywords, matches nodes by
name/title/id, and turns each match's direct relationships into a citation.

This is a lightweight, keyword-based query generator, not an LLM-based NL-to-Cypher translator
(that upgrade is the "Request parser and router (LangChain)" roadmap item). It is still real
generation: the WHERE/UNWIND parameters are built dynamically from the question, and the
resulting query is executed against Neo4j.
"""

import re
from typing import Any

from starlette.concurrency import run_in_threadpool

from src.clients import get_neo4j
from src.schemas import Citation, SourceType

MATCH_LIMIT = 5
NEIGHBOR_LIMIT = 8
MAX_KEYWORDS = 8

_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "who",
    "what",
    "which",
    "when",
    "where",
    "how",
    "does",
    "do",
    "did",
    "on",
    "in",
    "of",
    "to",
    "and",
    "or",
    "for",
    "with",
    "about",
    "tell",
    "me",
    "show",
    "list",
    "that",
    "this",
    "can",
    "you",
    "please",
    "i",
    "we",
    "our",
    "their",
    "his",
    "her",
    "its",
    "it",
    "there",
    "any",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")

# One hop out from every matched node, in either direction; relationship direction and role
# (present on WORKS_ON) are carried through so the citation can render "A -[:TYPE]-> B".
CYPHER = """
UNWIND $keywords AS kw
MATCH (n)
WHERE any(prop IN ['name', 'title', 'id'] WHERE toLower(coalesce(n[prop], '')) CONTAINS toLower(kw))
WITH DISTINCT n LIMIT $match_limit
OPTIONAL MATCH (n)-[r]-(m)
RETURN
  labels(n)[0] AS label,
  coalesce(n.name, n.title, n.id) AS name,
  collect(DISTINCT {
    type: type(r),
    role: r.role,
    outgoing: startNode(r) = n,
    other_label: labels(m)[0],
    other_name: coalesce(m.name, m.title, m.id)
  })[0..$neighbor_limit] AS rels
"""


def extract_keywords(question: str) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for word in _WORD_RE.findall(question):
        low = word.lower()
        if len(word) >= 3 and low not in _STOPWORDS and low not in seen:
            seen.add(low)
            keywords.append(word)
    return keywords[:MAX_KEYWORDS]


def build_cypher_query(question: str) -> tuple[str, dict[str, object]] | None:
    """Returns the Cypher query and its parameters, or None if the question has no usable keywords."""
    keywords = extract_keywords(question)
    if not keywords:
        return None
    return CYPHER, {"keywords": keywords, "match_limit": MATCH_LIMIT, "neighbor_limit": NEIGHBOR_LIMIT}


def _relationship_line(node: str, label: str, rel: dict[str, Any]) -> str | None:
    if rel.get("type") is None:
        return None
    role = f" {{{rel['role']}}}" if rel.get("role") else ""
    this_side = f"{node} ({label})"
    other_side = f"{rel['other_name']} ({rel['other_label']})"
    a, b = (this_side, other_side) if rel["outgoing"] else (other_side, this_side)
    return f"{a} -[:{rel['type']}{role}]-> {b}"


def _row_to_citation(row: dict[str, Any]) -> Citation:
    label, name = row["label"], row["name"]
    lines = [line for rel in row["rels"] if (line := _relationship_line(name, label, rel))]
    snippet = "\n".join(lines) if lines else f"{name} ({label}) has no recorded relationships."
    return Citation(id=f"graph-{label}-{name}", source_type="graph", title=f"{name} ({label})", snippet=snippet)


def _search(question: str) -> list[Citation]:
    generated = build_cypher_query(question)
    if generated is None:
        return []
    query, params = generated
    with get_neo4j().session() as session:
        rows = session.run(query, params).data()
    return [_row_to_citation(row) for row in rows if row["name"] is not None]


class Neo4jRetriever:
    source: SourceType = "graph"

    async def retrieve(self, query: str) -> list[Citation]:
        return await run_in_threadpool(_search, query)
