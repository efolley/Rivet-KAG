from fastapi import APIRouter
from pydantic import BaseModel

from src.api.deps import SettingsDep
from src.config import LLMProvider
from src.pipeline.models import MODEL_CATALOG, ModelOption

router = APIRouter(tags=["models"])


class ModelCatalogResponse(BaseModel):
    providers: dict[LLMProvider, list[ModelOption]]
    default_provider: LLMProvider
    default_model: str


@router.get("/models", response_model=ModelCatalogResponse)
async def list_models(settings: SettingsDep) -> ModelCatalogResponse:
    return ModelCatalogResponse(
        providers=MODEL_CATALOG, default_provider=settings.llm_provider, default_model=settings.llm_model
    )
