"""SQLAlchemy models for Postgres. Tables are created with `Base.metadata.create_all` (see
`src/db/engine.py`) rather than Alembic migrations — the simpler, demo-appropriate choice; a
real deployment would want versioned migrations instead.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ChatHistory(Base):
    """One row per /api/chat exchange — what a signed-in user can see of their own past chats."""

    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    question_masked: Mapped[str]
    answer: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ChatAuditLog(Base):
    """Append-only ops/compliance log — richer than chat_history, never shown back to the user.
    Only the PII-masked question is ever stored here; see the README's Observability and audit
    trail section. Writing to this table is best-effort (see src/api/routes/chat.py): a Postgres
    outage degrades observability, it must never break the chat response itself.
    """

    __tablename__ = "chat_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    question_masked: Mapped[str]
    answer: Mapped[str]
    sources_queried: Mapped[str]  # e.g. "vector,graph"
    citations_count: Mapped[int]
    outcome: Mapped[str]  # "success" | "guardrail_blocked" | "error"
    duration_ms: Mapped[float]
    # None whenever any stage's model is unpriced (see src/pipeline/pricing.py) or the request
    # never reached a cost-accounted stage (guardrail_blocked/error) -- never a guessed $0. Feeds
    # evals/check_alerts.py's "mean cost/request" condition.
    cost_usd: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DataEditProposal(Base):
    """A write the agent wants to make to Milvus or Neo4j, pending human review -- see README's
    "Agent actions". The agent (src/pipeline/answering/tools.py) can only ever INSERT a row
    here; nothing in Milvus/Neo4j changes until a human calls POST /api/actions/{id}/apply
    (src/api/routes/actions.py), which is the only code path that actually writes to either
    store. This table is the full audit trail of both the proposal and, once decided, the
    outcome -- there is no other record of agent-initiated data changes.
    """

    __tablename__ = "data_edit_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str]  # "vector_chunk" | "graph_property"
    target: Mapped[str]  # chunk id, or "Label:name:property"
    old_value: Mapped[str | None]
    new_value: Mapped[str]
    reason: Mapped[str]  # the agent's own stated reason, shown to the human reviewer verbatim
    status: Mapped[str] = mapped_column(default="pending")  # "pending" | "applied" | "rejected"
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    decided_at: Mapped[datetime | None]
    error: Mapped[str | None]  # set if an "applied" attempt actually failed against the store


class IngestionJob(Base):
    """One row per /api/files upload, tracking ingestion progress/outcome."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str]
    doc_type: Mapped[str]
    chunks_upserted: Mapped[int]
    status: Mapped[str]  # "completed" | "failed"
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
