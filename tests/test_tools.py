"""Mini test suite for src/pipeline/answering/tools.py: the LangChain tool wrappers correctly
read session_id from the contextvar (never from a model-supplied argument), record proposal ids
into the per-call collector, and turn a ProposalError into a plain string the model can see
rather than raising through the agent.
"""

import pytest

from src.db import DataEditProposal
from src.pipeline import actions
from src.pipeline.answering import tools


def _fake_proposal(proposal_id: int) -> DataEditProposal:
    p = DataEditProposal(session_id="s1", kind="vector_chunk", target="x::0", new_value="v", reason="r")
    p.id = proposal_id
    return p


async def test_propose_vector_chunk_update_tool_reads_session_id_from_contextvar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_propose(session_id: str, chunk_id: str, new_text: str, reason: str) -> DataEditProposal:
        captured["session_id"] = session_id
        return _fake_proposal(42)

    monkeypatch.setattr(actions, "propose_vector_chunk_update", fake_propose)
    token = tools.current_session_id.set("real-session-id")
    ids_token = tools.proposed_ids.set([])
    try:
        result = await tools.propose_vector_chunk_update.ainvoke(
            {"chunk_id": "x.md::0", "new_text": "new", "reason": "typo fix"}
        )
    finally:
        tools.current_session_id.reset(token)
        tools.proposed_ids.reset(ids_token)

    assert captured["session_id"] == "real-session-id"
    assert "#42" in result
    assert "NOT been changed yet" in result


async def test_propose_vector_chunk_update_tool_records_the_proposal_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_propose(session_id: str, chunk_id: str, new_text: str, reason: str) -> DataEditProposal:
        return _fake_proposal(7)

    monkeypatch.setattr(actions, "propose_vector_chunk_update", fake_propose)
    tools.current_session_id.set("s1")
    collector: list[int] = []
    tools.proposed_ids.set(collector)

    await tools.propose_vector_chunk_update.ainvoke({"chunk_id": "x.md::0", "new_text": "new", "reason": "r"})

    assert collector == [7]


async def test_propose_vector_chunk_update_tool_reports_an_error_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_propose(session_id: str, chunk_id: str, new_text: str, reason: str) -> DataEditProposal:
        raise actions.ProposalError("no such chunk")

    monkeypatch.setattr(actions, "propose_vector_chunk_update", fake_propose)
    tools.current_session_id.set("s1")
    tools.proposed_ids.set([])

    result = await tools.propose_vector_chunk_update.ainvoke({"chunk_id": "nope", "new_text": "new", "reason": "r"})

    assert "Could not propose this change" in result
    assert "no such chunk" in result


async def test_propose_graph_property_update_tool_records_the_proposal_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_propose(
        session_id: str, label: str, name: str, property: str, new_value: str, reason: str
    ) -> DataEditProposal:
        return _fake_proposal(9)

    monkeypatch.setattr(actions, "propose_graph_property_update", fake_propose)
    tools.current_session_id.set("s1")
    collector: list[int] = []
    tools.proposed_ids.set(collector)

    result = await tools.propose_graph_property_update.ainvoke(
        {"label": "Team", "name": "Data Platform", "property": "focus", "new_value": "x", "reason": "r"}
    )

    assert collector == [9]
    assert "#9" in result


async def test_propose_tool_does_not_raise_when_no_collector_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Calling the tool outside of DeepAgentAnswerer.answer()'s contextvar setup (e.g. a direct
    # unit test) must not blow up just because there's nothing to record the id into.
    async def fake_propose(session_id: str, chunk_id: str, new_text: str, reason: str) -> DataEditProposal:
        return _fake_proposal(1)

    monkeypatch.setattr(actions, "propose_vector_chunk_update", fake_propose)

    result = await tools.propose_vector_chunk_update.ainvoke({"chunk_id": "x", "new_text": "y", "reason": "r"})

    assert "#1" in result
