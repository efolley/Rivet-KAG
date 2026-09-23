"""Interfaces for each pipeline stage. Real implementations (LangChain, Milvus, Neo4j, DeepAgents) plug in here."""
from dataclasses import dataclass, field
from typing import Protocol

from src.schemas import Citation, SourceType


@dataclass
class Plan:
    intent: str
    query: str
    sources: list[SourceType] = field(default_factory=lambda: ["vector", "graph"])


class RequestParser(Protocol):
    async def parse(self, message: str) -> Plan: ...


class PIIMasker(Protocol):
    async def mask(self, text: str) -> str: ...


class Retriever(Protocol):
    source: SourceType

    async def retrieve(self, query: str) -> list[Citation]: ...


class Answerer(Protocol):
    async def answer(self, query: str, context: list[Citation]) -> str: ...
