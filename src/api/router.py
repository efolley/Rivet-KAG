from fastapi import APIRouter

from src.api.routes import auth, chat, data, files, health, models

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(auth.router)
api_router.include_router(files.router)
api_router.include_router(data.router)
api_router.include_router(models.router)
