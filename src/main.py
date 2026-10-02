import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import __version__
from src.api.router import api_router
from src.clients.kafka import shutdown_producer
from src.config import get_settings
from src.core.errors import register_error_handlers
from src.core.logging import setup_logging
from src.db import init_db

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    # Best-effort: a Postgres outage shouldn't stop the app from serving chat/retrieval, which
    # don't need it. Routes that do write to Postgres (chat history, the audit log, ingestion
    # jobs) are themselves written to degrade gracefully if a write fails later.
    try:
        await init_db()
    except Exception:
        log.exception("Could not reach Postgres on startup; history/audit logging will be skipped")
    yield
    await shutdown_producer()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="Rivet KAG", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
