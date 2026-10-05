"""Catalog of selectable answerer models, surfaced to the UI via GET /api/models. Deliberately
small -- the 1-2 cheapest/fastest model per provider, not the full lineup. Ollama entries are
free (local compute only); "cheapest" there means smallest/fastest rather than per-token price.
"""

from pydantic import BaseModel

from src.config import LLMProvider


class ModelOption(BaseModel):
    id: str
    label: str


MODEL_CATALOG: dict[LLMProvider, list[ModelOption]] = {
    "anthropic": [
        ModelOption(id="claude-haiku-4-5-20251001", label="Claude Haiku 4.5 (cheapest)"),
    ],
    "openai": [
        ModelOption(id="gpt-4.1-nano", label="GPT-4.1 nano (cheapest)"),
        ModelOption(id="gpt-4o-mini", label="GPT-4o mini"),
    ],
    "ollama": [
        ModelOption(id="llama3.2:latest", label="Llama 3.2 (local, free)"),
        ModelOption(id="qwen2.5:14b", label="Qwen2.5 14B (local, free)"),
    ],
}
