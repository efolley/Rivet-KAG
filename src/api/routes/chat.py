from fastapi import APIRouter

from src.api.deps import PipelineDep
from src.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, pipeline: PipelineDep) -> ChatResponse:
    return await pipeline.run(req)
