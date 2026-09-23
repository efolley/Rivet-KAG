from fastapi import APIRouter

from src.core.errors import NotImplementedFeature

router = APIRouter(prefix="/files", tags=["files"])


@router.post("")
async def upload_file() -> None:
    raise NotImplementedFeature("File upload/ingestion is on the roadmap (Phase 1).")
