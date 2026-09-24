from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pymilvus import MilvusClient

from src.config import get_settings

COLLECTION = "rivet_chunks"
EMBED_DIM = 384  # BAAI/bge-small-en-v1.5
REPO_ROOT = Path(__file__).resolve().parents[2]


def _local_path() -> Path | None:
    """Path of the Milvus Lite file, or None when MILVUS_URI points at a server."""
    uri = get_settings().milvus_uri
    if "://" in uri:
        return None
    path = Path(uri)
    path = path if path.is_absolute() else REPO_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def milvus_session() -> Iterator[MilvusClient]:
    """Open Milvus for one operation, then fully release it.

    Milvus Lite locks its file to a single process and MilvusClient.close() alone keeps the lock,
    so the embedded server is stopped explicitly. That lets the API and the upload CLI take turns.
    """
    path = _local_path()
    client = MilvusClient(uri=str(path) if path else get_settings().milvus_uri)
    try:
        if client.has_collection(COLLECTION):
            client.load_collection(COLLECTION)  # collections reopen in a released state
        yield client
    finally:
        client.close()
        if path:
            from milvus_lite.server_manager import server_manager_instance

            server_manager_instance.release_server(str(path))
