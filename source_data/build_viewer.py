"""Inline vector_data/ and graph_data/ into viewer_template.html -> index.html (stdlib only).

Usage: uv run python source_data/build_viewer.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
LABELS = {"employees": "Employee", "teams": "Team", "projects": "Project", "tools": "Tool", "documents": "Document"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build() -> dict:
    docs = [
        {"filename": p.name, "text": p.read_text(encoding="utf-8")}
        for p in sorted((ROOT / "vector_data").glob("*.md"))
    ]
    faq = read_csv(ROOT / "vector_data" / "support_faq.csv")
    nodes = []
    for stem, label in LABELS.items():
        for row in read_csv(ROOT / "graph_data" / f"{stem}.csv"):
            nodes.append({"id": row["id"], "label": label, "name": row.get("name") or row["title"], "props": row})
    edges = [
        {"type": r["type"], "source": r["start_id"], "target": r["end_id"], "role": r["role"]}
        for r in read_csv(ROOT / "graph_data" / "relationships.csv")
    ]
    ids = {n["id"] for n in nodes}
    dangling = [e for e in edges if e["source"] not in ids or e["target"] not in ids]
    if dangling:
        raise SystemExit(f"Relationships reference unknown nodes: {dangling}")
    return {"docs": docs, "faq": faq, "nodes": nodes, "edges": edges}


if __name__ == "__main__":
    data = json.dumps(build(), ensure_ascii=False).replace("</", "<\\/")
    html = (ROOT / "viewer_template.html").read_text(encoding="utf-8").replace("__DATA__", data)
    (ROOT / "index.html").write_text(html, encoding="utf-8")
    print("wrote source_data/index.html")
