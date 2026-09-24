import csv
import re
from datetime import date
from pathlib import Path

from src.clients import get_neo4j

NODE_FILES = {
    "employees.csv": "Employee",
    "teams.csv": "Team",
    "projects.csv": "Project",
    "tools.csv": "Tool",
    "documents.csv": "Document",
}
DATE_FIELDS = {"hired", "started"}
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # labels and relationship types cannot be Cypher parameters


def _ident(value: str) -> str:
    if not IDENT.match(value):
        raise ValueError(f"Invalid label or relationship type: {value!r}")
    return value


def _clean(props: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in props.items() if v not in ("", None)}


def merge_nodes(label: str, rows: list[dict[str, str]]) -> int:
    label = _ident(label)
    prepared: list[dict[str, object]] = []
    for raw in rows:
        row: dict[str, object] = dict(_clean(raw))
        if "id" not in row:
            raise ValueError("Every node needs an 'id' property")
        for field in DATE_FIELDS & row.keys():
            row[field] = date.fromisoformat(str(row[field]))
        prepared.append(row)
    with get_neo4j().session() as s:
        s.run(f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row", rows=prepared).consume()
    return len(prepared)


def merge_relationship(
    rel_type: str, start: tuple[str, str], end: tuple[str, str], props: dict[str, str] | None = None
) -> None:
    rel_type, sl, el = _ident(rel_type), _ident(start[0]), _ident(end[0])
    query = (
        f"MATCH (a:{sl} {{id: $a}}), (b:{el} {{id: $b}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) SET r += $props RETURN count(r) AS c"
    )
    with get_neo4j().session() as s:
        record = s.run(query, a=start[1], b=end[1], props=_clean(props or {})).single()
    if record is None or record["c"] == 0:
        raise ValueError(f"Could not find both nodes: {sl}:{start[1]} and {el}:{end[1]}")


def load_dir(directory: Path) -> tuple[int, int]:
    nodes = 0
    for filename, label in NODE_FILES.items():
        path = directory / filename
        if path.exists():
            with path.open(newline="", encoding="utf-8") as f:
                nodes += merge_nodes(label, list(csv.DictReader(f)))
    rels = 0
    path = directory / "relationships.csv"
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                merge_relationship(
                    r["type"],
                    (r["start_label"], r["start_id"]),
                    (r["end_label"], r["end_id"]),
                    {"role": r.get("role", "")},
                )
                rels += 1
    return nodes, rels


def clear() -> None:
    with get_neo4j().session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
