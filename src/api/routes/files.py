import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from src.api.deps import DbSessionDep
from src.db import IngestionJob
from src.ingestion import DOC_TYPES, SUPPORTED_SUFFIXES, ingest_upload
from src.schemas.files import FileUploadResponse

router = APIRouter(prefix="/files", tags=["files"])
log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # generous for this demo; not meant for large corpora


async def _record_job(
    db: AsyncSession, filename: str, doc_type: str, chunks_upserted: int, status: str, error: str | None
) -> None:
    """Best-effort, like the chat history/audit writes in chat.py: a Postgres outage must not
    fail the upload it's reporting on."""
    try:
        db.add(
            IngestionJob(
                filename=filename, doc_type=doc_type, chunks_upserted=chunks_upserted, status=status, error=error
            )
        )
        await db.commit()
    except Exception:
        log.warning("Could not write ingestion job record", exc_info=True)
        await db.rollback()


@router.post("", response_model=FileUploadResponse)
async def upload_file(file: UploadFile, db: DbSessionDep) -> FileUploadResponse:
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix!r}. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB for this demo).")

    doc_type = DOC_TYPES[suffix]
    # ingest_upload embeds and writes to Milvus; both are blocking, so run off the event loop.
    try:
        chunks_upserted, doc_type = await run_in_threadpool(ingest_upload, filename, data)
    except ValueError as e:
        await _record_job(db, filename, doc_type, 0, "failed", str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - surface ingestion/DB failures instead of a bare 500
        await _record_job(db, filename, doc_type, 0, "failed", str(e))
        raise HTTPException(status_code=502, detail=f"Ingestion failed: {e}") from e

    if chunks_upserted == 0:
        await _record_job(db, filename, doc_type, 0, "failed", "No text could be extracted from this file.")
        raise HTTPException(status_code=422, detail="No text could be extracted from this file.")

    await _record_job(db, filename, doc_type, chunks_upserted, "completed", None)
    return FileUploadResponse(filename=filename, doc_type=doc_type, chunks_upserted=chunks_upserted)
