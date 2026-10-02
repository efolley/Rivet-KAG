from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import decode_user_id
from src.config import Settings, get_settings
from src.db import get_session
from src.pipeline import Pipeline, build_pipeline


@lru_cache
def _pipeline() -> Pipeline:
    return build_pipeline(get_settings())


def get_pipeline() -> Pipeline:
    return _pipeline()


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
PipelineDep = Annotated[Pipeline, Depends(get_pipeline)]
DbSessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserIdDep = Annotated[int | None, Depends(get_current_user_id)]
RequiredUserIdDep = Annotated[int, Depends(require_current_user_id)]
