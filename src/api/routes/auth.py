from fastapi import APIRouter

from src.core.errors import NotImplementedFeature

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register() -> None:
    raise NotImplementedFeature("User auth is on the roadmap (Phase 3).")


@router.post("/login")
async def login() -> None:
    raise NotImplementedFeature("User auth is on the roadmap (Phase 3).")
