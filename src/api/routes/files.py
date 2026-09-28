from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from src.ingestion import SUPPORTED_SUFFIXES, ingest_upload
from src.schemas.files import FileUploadResponse

router = APIRouter(prefix="/files", tags=["files"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # generous for this demo; not meant for large corpora


@router.post("", response_model=FileUploadResponse)
async def upload_file(file: UploadFile) -> FileUploadResponse:
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

    # ingest_upload embeds and writes to Milvus; both are blocking, so run off the event loop.
    try:
        chunks_upserted, doc_type = await run_in_threadpool(ingest_upload, filename, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - surface ingestion/DB failures instead of a bare 500
        raise HTTPException(status_code=502, detail=f"Ingestion failed: {e}") from e

    if chunks_upserted == 0:
        raise HTTPException(status_code=422, detail="No text could be extracted from this file.")
    return FileUploadResponse(filename=filename, doc_type=doc_type, chunks_upserted=chunks_upserted)
