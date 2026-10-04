"""Write-capable actions the answerer agent can *propose* -- never apply directly. See README's
"Agent actions". Every function here either reads from Milvus/Neo4j (to capture `old_value` for
the audit trail) or inserts a pending `DataEditProposal` row; none of them writes to Milvus or
Neo4j. The only code that actually mutates either store is `apply_proposal`, called exclusively
from `POST /api/actions/{id}/apply` (src/api/routes/actions.py) -- a human action, never
something the agent can trigger on its own mid-conversation.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from src.clients import COLLECTION, get_neo4j, milvus_session
from src.db import DataEditProposal, get_session
from src.ingestion.embeddings import embed

log = logging.getLogger(__name__)

# Only labels that actually exist in this project's graph schema (source_data/graph_data/*.csv)
# -- Cypher can't parameterize a label, so whatever we interpolate into the query string must be
# checked against a fixed allowlist first, never passed through from the agent unchecked.
ALLOWED_GRAPH_LABELS = {"Employee", "Team", "Project", "Tool", "Document"}


class ProposalError(ValueError):
    """Raised for a proposal request that's invalid on its face (bad label, missing target) --
    distinct from a store failure at apply time, which is recorded on the row instead of raised."""


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    """`get_session()` is an async generator meant to be driven by FastAPI's own dependency
    injection (which resumes it after the request so its `async with ... as session: yield
    session` block can clean up). Calling it directly from here -- there's no FastAPI request to
    inject into, since an agent tool call has none -- and abandoning it after one `anext()`
    leaves that cleanup never run; under pytest-asyncio that raced with a *later* call's own
    session setup and corrupted both (caught live via tests/test_actions.py: every multi-call
    test failed with `IllegalStateChangeError`/`ResourceClosedError`). Driving the generator
    properly to its second (final) yield point, the same way FastAPI does, fixes it."""
    gen = get_session()
    db = await anext(gen)
    try:
        yield db
    finally:
        try:
            await anext(gen)
        except StopAsyncIteration:
            pass


async def _get_vector_chunk(chunk_id: str) -> dict[str, object] | None:
    def _fetch() -> dict[str, object] | None:
        with milvus_session() as client:
            if not client.has_collection(COLLECTION):
                return None
            rows = client.get(
                COLLECTION, ids=[chunk_id], output_fields=["text", "source", "doc_type", "heading", "chunk_index"]
            )
            return dict(rows[0]) if rows else None

    return await run_in_threadpool(_fetch)


async def propose_vector_chunk_update(session_id: str, chunk_id: str, new_text: str, reason: str) -> DataEditProposal:
    existing = await _get_vector_chunk(chunk_id)
    if existing is None:
        raise ProposalError(f"No vector chunk with id {chunk_id!r} exists to update.")

    proposal = DataEditProposal(
        session_id=session_id,
        kind="vector_chunk",
        target=chunk_id,
        old_value=str(existing["text"]),
        new_value=new_text,
        reason=reason,
    )
    async with _session() as db:
        db.add(proposal)
        await db.commit()
        await db.refresh(proposal)
    log.info("proposal id=%s kind=vector_chunk target=%s recorded (pending)", proposal.id, chunk_id)
    return proposal


async def _get_graph_property(label: str, name: str, prop: str) -> str | None:
    def _fetch() -> str | None:
        query = f"MATCH (n:{label}) WHERE n.name = $name OR n.id = $name RETURN n[$prop] AS value"
        with get_neo4j().session() as session:
            record = session.run(query, name=name, prop=prop).single()
            return None if record is None else record["value"]

    return await run_in_threadpool(_fetch)


async def propose_graph_property_update(
    session_id: str, label: str, name: str, property: str, new_value: str, reason: str
) -> DataEditProposal:
    if label not in ALLOWED_GRAPH_LABELS:
        raise ProposalError(f"{label!r} is not a known node label ({sorted(ALLOWED_GRAPH_LABELS)}).")

    old_value = await _get_graph_property(label, name, property)
    if old_value is None:
        raise ProposalError(f"No {label} node named {name!r} (or it has no {property!r} property) was found.")

    proposal = DataEditProposal(
        session_id=session_id,
        kind="graph_property",
        target=f"{label}:{name}:{property}",
        old_value=str(old_value),
        new_value=new_value,
        reason=reason,
    )
    async with _session() as db:
        db.add(proposal)
        await db.commit()
        await db.refresh(proposal)
    log.info("proposal id=%s kind=graph_property target=%s recorded (pending)", proposal.id, proposal.target)
    return proposal


async def list_proposals(status: str | None = None) -> list[DataEditProposal]:
    async with _session() as db:
        stmt = select(DataEditProposal).order_by(DataEditProposal.created_at.desc())
        if status is not None:
            stmt = stmt.where(DataEditProposal.status == status)
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def get_proposal(proposal_id: int) -> DataEditProposal | None:
    async with _session() as db:
        return await db.get(DataEditProposal, proposal_id)


def _apply_vector_chunk_update(chunk_id: str, new_text: str) -> None:
    with milvus_session() as client:
        rows = client.get(COLLECTION, ids=[chunk_id], output_fields=["source", "doc_type", "heading", "chunk_index"])
        if not rows:
            raise ProposalError(f"Chunk {chunk_id!r} no longer exists (it may have been re-ingested or deleted).")
        existing = rows[0]
        (vector,) = embed([new_text])
        client.upsert(
            COLLECTION,
            [
                {
                    "id": chunk_id,
                    "vector": vector,
                    "text": new_text,
                    "source": existing["source"],
                    "doc_type": existing["doc_type"],
                    "heading": existing["heading"],
                    "chunk_index": existing["chunk_index"],
                }
            ],
        )


def _apply_graph_property_update(label: str, name: str, prop: str, new_value: str) -> None:
    query = f"MATCH (n:{label}) WHERE n.name = $name OR n.id = $name SET n[$prop] = $value RETURN n"
    with get_neo4j().session() as session:
        record = session.run(query, name=name, prop=prop, value=new_value).single()
        if record is None:
            raise ProposalError(f"No {label} node named {name!r} was found when applying the change.")


async def apply_proposal(proposal_id: int) -> DataEditProposal:
    """The only function in this codebase that actually writes to Milvus or Neo4j on an
    agent-originated change. Only ever called from a human hitting
    POST /api/actions/{id}/apply."""
    async with _session() as db:
        proposal = await db.get(DataEditProposal, proposal_id)
        if proposal is None:
            raise ProposalError(f"No proposal with id {proposal_id}.")
        if proposal.status != "pending":
            raise ProposalError(f"Proposal {proposal_id} is already {proposal.status!r}, not pending.")

        try:
            if proposal.kind == "vector_chunk":
                await run_in_threadpool(_apply_vector_chunk_update, proposal.target, proposal.new_value)
            elif proposal.kind == "graph_property":
                label, name, prop = proposal.target.split(":", 2)
                await run_in_threadpool(_apply_graph_property_update, label, name, prop, proposal.new_value)
            else:  # pragma: no cover -- kind is only ever set by the two propose_* functions above
                raise ProposalError(f"Unknown proposal kind {proposal.kind!r}.")
        except ProposalError as e:
            proposal.status = "rejected"
            proposal.error = str(e)
        else:
            proposal.status = "applied"

        # .replace(tzinfo=None): asyncpg returns func.now() as a tz-aware timestamptz
        # regardless of decided_at's own (naive) column type, and rejects the bind param
        # outright if it's left aware -- the same bug already hit (and documented) in
        # src/api/routes/chat.py's _session_spend_24h; caught here live via `make dev`, not by
        # the (SQLite-backed) test suite, which doesn't reproduce asyncpg's specific behavior.
        proposal.decided_at = (await db.execute(select(func.now()))).scalar_one().replace(tzinfo=None)
        await db.commit()
        await db.refresh(proposal)
        log.info("proposal id=%s %s", proposal.id, proposal.status)
        return proposal


async def reject_proposal(proposal_id: int) -> DataEditProposal:
    async with _session() as db:
        proposal = await db.get(DataEditProposal, proposal_id)
        if proposal is None:
            raise ProposalError(f"No proposal with id {proposal_id}.")
        if proposal.status != "pending":
            raise ProposalError(f"Proposal {proposal_id} is already {proposal.status!r}, not pending.")

        proposal.status = "rejected"
        proposal.decided_at = (await db.execute(select(func.now()))).scalar_one().replace(tzinfo=None)
        await db.commit()
        await db.refresh(proposal)
        log.info("proposal id=%s rejected", proposal.id)
        return proposal
