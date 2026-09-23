from fastapi import APIRouter

from src.api.routes import auth, chat, files, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(auth.router)
api_router.include_router(files.router)
