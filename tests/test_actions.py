"""Mini test suite for src/pipeline/actions.py: proposing a vector/graph change never writes
to Milvus/Neo4j (only reads, to capture old_value), applying one does exactly the write it
proposed, and a decided (applied/rejected) proposal can't be re-decided. Milvus/Neo4j are
mocked; Postgres is the real-in-memory-SQLite `db_session` fixture (see tests/conftest.py).
"""

import pytest
from sqlalchemy import select

from src.db import DataEditProposal
from src.pipeline import actions


class FakeMilvusClient:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row
        self.upserted: list[dict[str, object]] = []

    def has_collection(self, name: str) -> bool:
        return True

    def get(self, collection: str, ids: list[str], output_fields: list[str]) -> list[dict[str, object]]:
        return [self._row] if self._row else []

    def upsert(self, collection: str, rows: list[dict[str, object]]) -> None:
        self.upserted.extend(rows)

    def __enter__(self) -> "FakeMilvusClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeNeo4jSession:
    def __init__(self, record: dict[str, object] | None) -> None:
        self._record = record
        self.queries: list[tuple[str, dict[str, object]]] = []

    def run(self, query: str, **params: object) -> "FakeNeo4jSession":
        self.queries.append((query, params))
        return self

    def single(self) -> dict[str, object] | None:
        return self._record


class FakeNeo4jDriver:
    def __init__(self, record: dict[str, object] | None) -> None:
        self._record = record
        self.last_session: FakeNeo4jSession | None = None

    def session(self) -> "FakeNeo4jDriver":
        self.last_session = FakeNeo4jSession(self._record)
        return self  # type: ignore[return-value]

    def __enter__(self) -> FakeNeo4jSession:
        assert self.last_session is not None
        return self.last_session

    def __exit__(self, *exc: object) -> None:
        return None


async def test_propose_vector_chunk_update_only_reads_never_writes(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    client = FakeMilvusClient({"text": "old text", "source": "x.md", "doc_type": "md", "heading": "", "chunk_index": 0})
    monkeypatch.setattr("src.pipeline.actions.milvus_session", lambda: client)

    proposal = await actions.propose_vector_chunk_update("s1", "x.md::0", "new text", "user asked for a correction")

    assert proposal.status == "pending"
    assert proposal.old_value == "old text"
    assert proposal.new_value == "new text"
    assert client.upserted == []  # the whole point: proposing never writes


async def test_propose_vector_chunk_update_rejects_an_unknown_chunk(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    monkeypatch.setattr("src.pipeline.actions.milvus_session", lambda: FakeMilvusClient(None))

    with pytest.raises(actions.ProposalError):
        await actions.propose_vector_chunk_update("s1", "missing::0", "new text", "reason")


async def test_propose_graph_property_update_only_reads_never_writes(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    driver = FakeNeo4jDriver({"value": "old focus"})
    monkeypatch.setattr("src.pipeline.actions.get_neo4j", lambda: driver)

    proposal = await actions.propose_graph_property_update("s1", "Team", "Data Platform", "focus", "new focus", "why")

    assert proposal.status == "pending"
    assert proposal.old_value == "old focus"
    assert proposal.target == "Team:Data Platform:focus"
    assert "SET" not in driver.last_session.queries[0][0]  # a read-only MATCH/RETURN, no write


async def test_propose_graph_property_update_rejects_an_unknown_label(db_session: object) -> None:
    with pytest.raises(actions.ProposalError):
        await actions.propose_graph_property_update("s1", "NotARealLabel", "x", "prop", "value", "reason")


async def test_propose_graph_property_update_rejects_a_missing_node(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    monkeypatch.setattr("src.pipeline.actions.get_neo4j", lambda: FakeNeo4jDriver(None))

    with pytest.raises(actions.ProposalError):
        await actions.propose_graph_property_update("s1", "Team", "Nonexistent", "focus", "value", "reason")


async def test_apply_proposal_performs_the_real_vector_write(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    client = FakeMilvusClient({"text": "old", "source": "x.md", "doc_type": "md", "heading": "", "chunk_index": 0})
    monkeypatch.setattr("src.pipeline.actions.milvus_session", lambda: client)
    monkeypatch.setattr("src.pipeline.actions.embed", lambda texts: [[0.1, 0.2]])

    proposal = await actions.propose_vector_chunk_update("s1", "x.md::0", "new text", "reason")
    applied = await actions.apply_proposal(proposal.id)

    assert applied.status == "applied"
    assert client.upserted == [
        {
            "id": "x.md::0",
            "vector": [0.1, 0.2],
            "text": "new text",
            "source": "x.md",
            "doc_type": "md",
            "heading": "",
            "chunk_index": 0,
        }
    ]


async def test_apply_proposal_performs_the_real_graph_write(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    driver = FakeNeo4jDriver({"value": "old"})
    monkeypatch.setattr("src.pipeline.actions.get_neo4j", lambda: driver)

    proposal = await actions.propose_graph_property_update("s1", "Team", "Data Platform", "focus", "new focus", "why")
    applied = await actions.apply_proposal(proposal.id)

    assert applied.status == "applied"
    apply_query = driver.last_session.queries[-1][0]
    assert "SET n[$prop] = $value" in apply_query


async def test_apply_proposal_rejects_a_proposal_already_decided(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    client = FakeMilvusClient({"text": "old", "source": "x.md", "doc_type": "md", "heading": "", "chunk_index": 0})
    monkeypatch.setattr("src.pipeline.actions.milvus_session", lambda: client)
    monkeypatch.setattr("src.pipeline.actions.embed", lambda texts: [[0.1, 0.2]])

    proposal = await actions.propose_vector_chunk_update("s1", "x.md::0", "new text", "reason")
    await actions.apply_proposal(proposal.id)

    with pytest.raises(actions.ProposalError):
        await actions.apply_proposal(proposal.id)


async def test_apply_proposal_raises_for_an_unknown_id(db_session: object) -> None:
    with pytest.raises(actions.ProposalError):
        await actions.apply_proposal(999999)


async def test_reject_proposal_marks_it_rejected_without_writing(
    monkeypatch: pytest.MonkeyPatch, db_session: object
) -> None:
    client = FakeMilvusClient({"text": "old", "source": "x.md", "doc_type": "md", "heading": "", "chunk_index": 0})
    monkeypatch.setattr("src.pipeline.actions.milvus_session", lambda: client)

    proposal = await actions.propose_vector_chunk_update("s1", "x.md::0", "new text", "reason")
    rejected = await actions.reject_proposal(proposal.id)

    assert rejected.status == "rejected"
    assert client.upserted == []


async def test_list_proposals_filters_by_status(monkeypatch: pytest.MonkeyPatch, db_session: object) -> None:
    client = FakeMilvusClient({"text": "old", "source": "x.md", "doc_type": "md", "heading": "", "chunk_index": 0})
    monkeypatch.setattr("src.pipeline.actions.milvus_session", lambda: client)

    p1 = await actions.propose_vector_chunk_update("s1", "x.md::0", "a", "r")
    p2 = await actions.propose_vector_chunk_update("s1", "x.md::0", "b", "r")
    await actions.reject_proposal(p2.id)

    pending = await actions.list_proposals(status="pending")
    assert [p.id for p in pending] == [p1.id]

    all_proposals = await actions.list_proposals()
    assert {p.id for p in all_proposals} == {p1.id, p2.id}


async def test_data_edit_proposal_round_trips_through_postgres(db_session: object) -> None:
    # Sanity check on the raw model/table, independent of the actions.py helpers above.
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db_session, AsyncSession)
    db_session.add(DataEditProposal(session_id="s1", kind="vector_chunk", target="x::0", new_value="v", reason="r"))
    await db_session.commit()
    result = await db_session.execute(select(DataEditProposal).where(DataEditProposal.session_id == "s1"))
    row = result.scalar_one()
    assert row.status == "pending"
    assert row.old_value is None
