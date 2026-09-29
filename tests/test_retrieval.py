"""Mini test suite for the real retrievers: Cypher generation, and mapping DB rows to citations
for both Milvus and Neo4j. Everything is mocked, so no live database or embedding model is needed.
"""

import pytest

from src.config import Settings
from src.pipeline.factory import build_pipeline
from src.pipeline.retrieval.milvus import MilvusRetriever
from src.pipeline.retrieval.neo4j import Neo4jRetriever, build_cypher_query, extract_keywords


def test_cypher_generation_extracts_keywords_and_skips_when_none_found() -> None:
    assert extract_keywords("Who leads the Data Platform team?") == ["leads", "Data", "Platform", "team"]
    assert extract_keywords("Is it on?") == []
    assert build_cypher_query("Who is that?") is None

    query, params = build_cypher_query("What tools does Beacon use?")  # type: ignore[misc]
    assert "UNWIND $keywords" in query
    assert params["keywords"] == ["tools", "Beacon", "use"]


async def test_neo4j_retriever_labels_each_side_of_a_relationship_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: the first version of this mapping attached the *other* node's label to
    # whichever side printed second, so an incoming relationship showed the wrong label.
    row = {
        "label": "Team",
        "name": "Data Platform",
        "rels": [
            {"type": "LEADS", "role": None, "outgoing": False, "other_label": "Employee", "other_name": "Priya Nair"},
            {"type": "OWNS", "role": None, "outgoing": True, "other_label": "Project", "other_name": "Atlas"},
        ],
    }

    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def run(self, query: str, params: dict[str, object]) -> "FakeSession":
            return self

        def data(self) -> list[dict[str, object]]:
            return [row]

    class FakeDriver:
        def session(self) -> FakeSession:
            return FakeSession()

    monkeypatch.setattr("src.pipeline.retrieval.neo4j.get_neo4j", lambda: FakeDriver())

    citations = await Neo4jRetriever().retrieve("Who leads the Data Platform team?")

    assert len(citations) == 1
    c = citations[0]
    assert c.source_type == "graph"
    assert c.title == "Data Platform (Team)"
    assert "Priya Nair (Employee) -[:LEADS]-> Data Platform (Team)" in c.snippet
    assert "Data Platform (Team) -[:OWNS]-> Atlas (Project)" in c.snippet


async def test_milvus_retriever_maps_hits_to_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    hits = [
        [
            {
                "id": "vpn_and_access_policy.md::0",
                "distance": 0.8341,
                "entity": {
                    "source": "vpn_and_access_policy.md",
                    "heading": "Who gets VPN access",
                    "text": "VPN access is granted after security training.",
                },
            }
        ]
    ]

    class FakeClient:
        def has_collection(self, name: str) -> bool:
            return True

        def search(self, *args: object, **kwargs: object) -> list[list[dict[str, object]]]:
            return hits

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr("src.pipeline.retrieval.milvus.embed", lambda texts: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr("src.pipeline.retrieval.milvus.milvus_session", lambda: FakeClient())

    citations = await MilvusRetriever().retrieve("When do new hires get VPN access?")

    assert len(citations) == 1
    c = citations[0]
    assert c.id == "vpn_and_access_policy.md::0"
    assert c.source_type == "vector"
    assert c.title == "vpn_and_access_policy.md — Who gets VPN access"
    assert c.snippet == "VPN access is granted after security training."
    assert c.score == 0.834


async def test_milvus_retriever_returns_empty_when_collection_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def has_collection(self, name: str) -> bool:
            return False

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr("src.pipeline.retrieval.milvus.embed", lambda texts: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr("src.pipeline.retrieval.milvus.milvus_session", lambda: FakeClient())

    assert await MilvusRetriever().retrieve("anything") == []


def test_factory_uses_real_retrievers_only_when_stubs_disabled() -> None:
    stub_pipeline = build_pipeline(Settings(use_stubs=True))
    real_pipeline = build_pipeline(Settings(use_stubs=False))

    assert {type(r).__name__ for r in stub_pipeline._retrievers.values()} == {
        "StubVectorRetriever",
        "StubGraphRetriever",
    }
    assert {type(r).__name__ for r in real_pipeline._retrievers.values()} == {"MilvusRetriever", "Neo4jRetriever"}
