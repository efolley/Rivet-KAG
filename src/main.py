from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import __version__
from src.api.router import api_router
from src.config import get_settings
from src.core.errors import register_error_handlers
from src.core.logging import setup_logging


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="Rivet KAG", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
