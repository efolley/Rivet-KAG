import json
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from src.clients import COLLECTION, get_neo4j, milvus_session
from src.schemas.data import (
    DataOverview,
    GraphData,
    GraphEdge,
    GraphNode,
    GraphOverview,
    SourceSummary,
    VectorChunk,
    VectorChunkPage,
    VectorOverview,
)

router = APIRouter(prefix="/data", tags=["data"])

MILVUS_QUERY_CAP = 16384  # Milvus limit on rows returned by one query; fine for demo-sized data
GRAPH_NODE_CAP = 1000
CHUNK_FIELDS = ["source", "doc_type", "heading", "chunk_index", "text"]

# Sync endpoints: FastAPI runs them in a threadpool, which suits the blocking DB drivers.


def _vector_overview() -> VectorOverview:
    try:
        with milvus_session() as client:
            if not client.has_collection(COLLECTION):
                return VectorOverview(available=True, collection=COLLECTION)
            rows = [
                dict(r)
                for r in client.query(
                    COLLECTION, filter="", output_fields=["source", "doc_type"], limit=MILVUS_QUERY_CAP
                )
            ]
    except Exception as e:  # noqa: BLE001 - surface any connection problem to the UI instead of a 500
        return VectorOverview(available=False, error=str(e), collection=COLLECTION)
    counts = Counter((r["source"], r["doc_type"]) for r in rows)
    sources = [SourceSummary(source=s, doc_type=t, chunks=n) for (s, t), n in sorted(counts.items())]
    return VectorOverview(available=True, collection=COLLECTION, total_chunks=len(rows), sources=sources)


def _graph_overview() -> GraphOverview:
    try:
        with get_neo4j().session() as s:
            nodes = s.run("MATCH (n) RETURN labels(n)[0] AS k, count(*) AS c ORDER BY k").data()
            rels = s.run("MATCH ()-[r]->() RETURN type(r) AS k, count(*) AS c ORDER BY k").data()
    except Exception as e:  # noqa: BLE001
        return GraphOverview(available=False, error=str(e))
    return GraphOverview(
        available=True,
        node_counts={r["k"]: r["c"] for r in nodes},
        relationship_counts={r["k"]: r["c"] for r in rels},
    )


@router.get("/overview", response_model=DataOverview)
def overview() -> DataOverview:
    return DataOverview(vector=_vector_overview(), graph=_graph_overview())


@router.get("/vector/chunks", response_model=VectorChunkPage)
def vector_chunks(
    source: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VectorChunkPage:
    try:
        with milvus_session() as client:
            if not client.has_collection(COLLECTION):
                return VectorChunkPage(total=0, items=[])
            expr = f"source == {json.dumps(source)}" if source else ""
            rows = client.query(COLLECTION, filter=expr, output_fields=["id", *CHUNK_FIELDS], limit=MILVUS_QUERY_CAP)
            rows = [dict(r) for r in rows]  # materialise before the client closes
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Milvus unavailable: {e}") from e
    rows = sorted(rows, key=lambda r: (r["source"], r["chunk_index"]))
    return VectorChunkPage(total=len(rows), items=[VectorChunk(**r) for r in rows[offset : offset + limit]])


def _jsonable(value: Any) -> Any:
    return value if isinstance(value, str | int | float | bool | None) else str(value)


@router.get("/graph", response_model=GraphData)
def graph() -> GraphData:
    try:
        with get_neo4j().session() as s:
            node_rows = s.run(
                "MATCH (n) RETURN labels(n)[0] AS label, properties(n) AS props ORDER BY label, n.id LIMIT $cap",
                cap=GRAPH_NODE_CAP,
            ).data()
            edge_rows = s.run(
                "MATCH (a)-[r]->(b) WHERE a.id IS NOT NULL AND b.id IS NOT NULL "
                "RETURN type(r) AS type, a.id AS source, b.id AS target, r.role AS role ORDER BY type, source, target"
            ).data()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Neo4j unavailable: {e}") from e
    nodes = []
    for r in node_rows:
        props = {k: _jsonable(v) for k, v in r["props"].items()}
        name = str(props.get("name") or props.get("title") or props.get("id", ""))
        nodes.append(GraphNode(id=str(props.get("id", "")), label=r["label"], name=name, props=props))
    ids = {n.id for n in nodes}
    edges = [GraphEdge(**e) for e in edge_rows if e["source"] in ids and e["target"] in ids]
    return GraphData(nodes=nodes, edges=edges)
