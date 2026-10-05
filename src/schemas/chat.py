from typing import Literal

from pydantic import BaseModel, Field

from src.config import LLMProvider

SourceType = Literal["vector", "graph"]


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)
    # Overrides the answerer's model backend for just this request; None means "use the
    # server's configured default" (settings.llm_provider / settings.llm_model).
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None
    # Opt-in, off by default: when True, the answerer agent gets write-capable tools that can
    # propose a Milvus/Neo4j change (never apply one directly) -- see README's "Agent actions".
    # False means those tools aren't bound to the agent at all, not just "discouraged".
    allow_actions: bool = False


class Citation(BaseModel):
    id: str
    source_type: SourceType
    title: str
    snippet: str
    score: float | None = None


class StageTrace(BaseModel):
    name: str
    detail: str
    duration_ms: float
    # Cost accounting (see src/pipeline/pricing.py): populated for LLM-backed stages (parse,
    # answer) when the model has a known price; None for everything else, including an unlisted
    # model -- "unknown", never guessed as $0.
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    budget_rejected: bool = False


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[StageTrace]
    # Sum of each stage's cost_usd; None if any stage's cost is unknown (an unpriced model) --
    # summing unknowns as 0 would understate the real spend.
    total_cost_usd: float | None = None
    # ids of any pending DataEditProposal rows the agent created this turn (empty unless
    # req.allow_actions was True) -- nothing has changed in Milvus/Neo4j yet, see
    # GET /api/actions and POST /api/actions/{id}/apply.
    proposed_action_ids: list[int] = []
