from typing import Any

from pydantic import BaseModel


class SourceSummary(BaseModel):
    source: str
    doc_type: str
    chunks: int


class VectorOverview(BaseModel):
    available: bool
    error: str | None = None
    collection: str
    total_chunks: int = 0
    sources: list[SourceSummary] = []


class GraphOverview(BaseModel):
    available: bool
    error: str | None = None
    node_counts: dict[str, int] = {}
    relationship_counts: dict[str, int] = {}


class DataOverview(BaseModel):
    vector: VectorOverview
    graph: GraphOverview


class VectorChunk(BaseModel):
    id: str
    source: str
    doc_type: str
    heading: str
    chunk_index: int
    text: str


class VectorChunkPage(BaseModel):
    total: int
    items: list[VectorChunk]


class GraphNode(BaseModel):
    id: str
    label: str
    name: str
    props: dict[str, Any]


class GraphEdge(BaseModel):
    type: str
    source: str
    target: str
    role: str | None = None


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
