from pathlib import Path

from pymilvus import MilvusClient

from src.clients import COLLECTION, EMBED_DIM, milvus_session
from utils.chunking import Chunk, chunk_file, chunk_text
from utils.embeddings import embed


def _ensure_collection(client: MilvusClient) -> None:
    if not client.has_collection(COLLECTION):
        client.create_collection(
            COLLECTION, dimension=EMBED_DIM, metric_type="COSINE", id_type="string", max_length=256
        )


def upsert_chunks(chunks: list[Chunk]) -> int:
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


def load_paths(paths: list[Path]) -> int:
    files = [f for p in paths for f in (sorted(p.iterdir()) if p.is_dir() else [p])]
    chunks = [c for f in files if f.suffix.lower() in {".md", ".markdown", ".csv", ".txt"} for c in chunk_file(f)]
    return upsert_chunks(chunks)


def load_text(text: str, source: str) -> int:
    return upsert_chunks(chunk_text(source, text))


def clear() -> None:
    with milvus_session() as client:
        if client.has_collection(COLLECTION):
            client.drop_collection(COLLECTION)
