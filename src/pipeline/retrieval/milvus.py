"""Real vector retriever: embed the question and run an ANN search over the ingested chunks."""

from starlette.concurrency import run_in_threadpool

from src.clients import COLLECTION, milvus_session
from src.ingestion.embeddings import embed
from src.schemas import Citation, SourceType

TOP_K = 4


def _search(query: str) -> list[Citation]:
    (vector,) = embed([query])
    with milvus_session() as client:
        if not client.has_collection(COLLECTION):
            return []
        hits = client.search(COLLECTION, data=[vector], limit=TOP_K, output_fields=["source", "heading", "text"])[0]
    citations = []
    for h in hits:
        entity = h["entity"]
        title = entity["source"] + (f" — {entity['heading']}" if entity["heading"] else "")
        citations.append(
            Citation(
                id=str(h["id"]),
                source_type="vector",
                title=title,
                snippet=entity["text"],
                score=round(h["distance"], 3),
            )
        )
    return citations


class MilvusRetriever:
    source: SourceType = "vector"

    async def retrieve(self, query: str) -> list[Citation]:
        return await run_in_threadpool(_search, query)
