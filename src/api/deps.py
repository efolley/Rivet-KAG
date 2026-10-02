from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import decode_user_id
from src.config import LLMProvider, Settings, get_settings
from src.db import get_session
from src.pipeline import Pipeline, build_pipeline


@lru_cache
def _pipeline_for(provider: LLMProvider | None, model: str | None) -> Pipeline:
    # Cached per (provider, model) pair so picking a model in the UI doesn't rebuild the
    # DeepAgents graph (and its model client) on every request -- retrievers/parser/masker are
    # cheap to duplicate per pipeline, so there's no reuse-vs-rebuild tradeoff worth making here.
    settings = get_settings()
    updates: dict[str, str] = {}
    if provider is not None:
        updates["llm_provider"] = provider
    if model is not None:
        updates["llm_model"] = model
    if updates:
        settings = settings.model_copy(update=updates)
    return build_pipeline(settings)


def get_pipeline_for(provider: LLMProvider | None, model: str | None) -> Pipeline:
    """Resolves the pipeline for a chat request, honoring a per-request model override
    (ChatRequest.llm_provider/llm_model) and falling back to the server's configured default
    when neither is set."""
    return _pipeline_for(provider, model)


async def get_current_user_id(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> int | None:
    """The authenticated user's id, or None for an anonymous request. Optional by design: chat
    and uploads work with or without a token, so logged-in users just get their activity
    attributed to their account instead of being anonymous.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    return decode_user_id(token, settings)


async def require_current_user_id(user_id: Annotated[int | None, Depends(get_current_user_id)]) -> int:
    if user_id is None:
        raise HTTPException(status_code=401, detail="A valid bearer token is required.")
    return user_id


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserIdDep = Annotated[int | None, Depends(get_current_user_id)]
RequiredUserIdDep = Annotated[int, Depends(require_current_user_id)]
