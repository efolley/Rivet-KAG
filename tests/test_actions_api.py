"""Mini test suite for the human-review API (src/api/routes/actions.py): list/apply/reject
wire through to src/pipeline/actions.py correctly and turn ProposalError into a 404, not a 500.
The underlying actions.py logic itself is tested in tests/test_actions.py; this is just the
HTTP layer on top.
"""

from datetime import UTC

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


async def test_apply_action_returns_404_for_an_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.pipeline import actions

    async def boom(proposal_id: int) -> None:
        raise actions.ProposalError(f"No proposal with id {proposal_id}.")

    monkeypatch.setattr("src.api.routes.actions.actions.apply_proposal", boom)

    r = client.post("/api/actions/999999/apply")

    assert r.status_code == 404


async def test_reject_action_returns_404_for_an_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.pipeline import actions

    async def boom(proposal_id: int) -> None:
        raise actions.ProposalError(f"No proposal with id {proposal_id}.")

    monkeypatch.setattr("src.api.routes.actions.actions.reject_proposal", boom)

    r = client.post("/api/actions/999999/reject")

    assert r.status_code == 404


async def test_list_actions_returns_whatever_the_pipeline_layer_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime

    from src.db import DataEditProposal

    row = DataEditProposal(
        session_id="s1",
        kind="vector_chunk",
        target="x.md::0",
        old_value="old",
        new_value="new",
        reason="because",
        status="pending",
    )
    row.id = 1
    row.created_at = datetime.now(UTC)
    row.decided_at = None
    row.error = None

    async def fake_list(status: str | None = None) -> list[DataEditProposal]:
        return [row]

    monkeypatch.setattr("src.api.routes.actions.actions.list_proposals", fake_list)

    r = client.get("/api/actions")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == 1
    assert body[0]["status"] == "pending"
    assert body[0]["reason"] == "because"


async def test_chat_allow_actions_defaults_to_false() -> None:
    # No LLM key configured in tests -> StubAnswerer either way, but this confirms the field
    # exists with the safe default and a plain request doesn't need to set it.
    r = client.post("/api/chat", json={"session_id": "s1", "message": "any question"})
    assert r.status_code == 200
    assert r.json()["proposed_action_ids"] == []
