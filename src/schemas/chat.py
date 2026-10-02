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


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[StageTrace]
