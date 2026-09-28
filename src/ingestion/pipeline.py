"""Embed chunks and upsert them into Milvus. Used by both the upload CLI and the /api/files endpoint."""

import tempfile
from pathlib import Path

from pymilvus import MilvusClient

from src.clients import COLLECTION, EMBED_DIM, milvus_session
from src.ingestion.embeddings import embed
from src.ingestion.loaders import DOC_TYPES, SUPPORTED_SUFFIXES, Chunk, chunk_file, chunk_text


def _ensure_collection(client: MilvusClient) -> None:
    if not client.has_collection(COLLECTION):
        client.create_collection(
            COLLECTION, dimension=EMBED_DIM, metric_type="COSINE", id_type="string", max_length=256
        )


def ingest_chunks(chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    vectors = embed([c.text for c in chunks])
    rows = [
        {
            "id": c.id,
            "vector": v,
            "text": c.text,
            "source": c.source,
            "doc_type": c.doc_type,
            "heading": c.heading,
            "chunk_index": c.chunk_index,
        }
        for c, v in zip(chunks, vectors, strict=True)
    ]
    with milvus_session() as client:
        _ensure_collection(client)
        client.upsert(COLLECTION, rows)
    return len(rows)


def ingest_paths(paths: list[Path]) -> int:
    files = [f for p in paths for f in (sorted(p.iterdir()) if p.is_dir() else [p])]
    chunks = [c for f in files if f.suffix.lower() in SUPPORTED_SUFFIXES for c in chunk_file(f)]
    return ingest_chunks(chunks)


def ingest_text(text: str, source: str) -> int:
    return ingest_chunks(chunk_text(text, source))


def ingest_upload(filename: str, data: bytes) -> tuple[int, str]:
    """Chunk and embed an in-memory upload. Returns (chunks upserted, doc_type)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {suffix!r} (supported: {', '.join(sorted(SUPPORTED_SUFFIXES))})")
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        chunks = chunk_file(Path(tmp.name), source=filename)
    return ingest_chunks(chunks), DOC_TYPES[suffix]


def clear_vector_store() -> None:
    with milvus_session() as client:
        if client.has_collection(COLLECTION):
            client.drop_collection(COLLECTION)
