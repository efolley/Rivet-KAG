"""Upload data into Milvus (vectors) and Neo4j (graph).

Examples (run from the repo root):
  uv run python -m utils.upload all                          # load everything in source_data/
  uv run python -m utils.upload vector files docs/a.md notes.csv report.xlsx manual.pdf
  uv run python -m utils.upload vector text "Refunds take 5 days." --source refunds_note
  uv run python -m utils.upload graph csv source_data/graph_data
  uv run python -m utils.upload graph node Employee id=E13 name="Ada Lovelace" title=Engineer
  uv run python -m utils.upload graph rel MEMBER_OF Employee:E13 Team:TM1
  uv run python -m utils.upload clear all --yes
"""

import argparse
import sys
from pathlib import Path

from src import ingestion
from utils import neo4j_loader

SOURCE_DATA = Path(__file__).resolve().parent.parent / "source_data"


def parse_kv(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in pairs:
        key, sep, value = p.partition("=")
        if not sep or not key:
            raise SystemExit(f"Expected key=value, got {p!r}")
        out[key] = value
    return out


def parse_ref(ref: str) -> tuple[str, str]:
    label, sep, node_id = ref.partition(":")
    if not sep or not node_id:
        raise SystemExit(f"Expected Label:id, got {ref!r}")
    return label, node_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m utils.upload", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="target", required=True)

    sub.add_parser("all", help="load source_data/ into both databases")

    vec = sub.add_parser("vector", help="Milvus").add_subparsers(dest="action", required=True)
    files = vec.add_parser("files", help="embed and upsert .md/.csv/.xlsx/.pdf/.txt files or folders")
    files.add_argument("paths", nargs="+", type=Path)
    text = vec.add_parser("text", help="embed and upsert a piece of text")
    text.add_argument("text")
    text.add_argument("--source", required=True, help="name shown as the source, e.g. my_note")

    graph = sub.add_parser("graph", help="Neo4j").add_subparsers(dest="action", required=True)
    csv_cmd = graph.add_parser("csv", help="load a folder of node CSVs plus relationships.csv")
    csv_cmd.add_argument("directory", type=Path)
    node = graph.add_parser("node", help="create or update one node")
    node.add_argument("label")
    node.add_argument("props", nargs="+", help="key=value pairs; 'id' is required")
    rel = graph.add_parser("rel", help="create one relationship between existing nodes")
    rel.add_argument("type")
    rel.add_argument("start", help="Label:id")
    rel.add_argument("end", help="Label:id")
    rel.add_argument("--role", default="")

    clear = sub.add_parser("clear", help="delete data")
    clear.add_argument("which", choices=["vector", "graph", "all"])
    clear.add_argument("--yes", action="store_true", help="required to confirm")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except ValueError as e:
        sys.exit(f"Error: {e}")


def run(args: argparse.Namespace) -> None:

    if args.target == "all":
        n = ingestion.ingest_paths([SOURCE_DATA / "vector_data"])
        nodes, rels = neo4j_loader.load_dir(SOURCE_DATA / "graph_data")
        print(f"Milvus: upserted {n} chunks. Neo4j: merged {nodes} nodes, {rels} relationships.")
    elif args.target == "vector":
        if args.action == "files":
            print(f"Upserted {ingestion.ingest_paths(args.paths)} chunks into Milvus.")
        else:
            print(f"Upserted {ingestion.ingest_text(args.text, args.source)} chunk into Milvus.")
    elif args.target == "graph":
        if args.action == "csv":
            nodes, rels = neo4j_loader.load_dir(args.directory)
            print(f"Merged {nodes} nodes and {rels} relationships into Neo4j.")
        elif args.action == "node":
            neo4j_loader.merge_nodes(args.label, [parse_kv(args.props)])
            print("Node merged.")
        else:
            neo4j_loader.merge_relationship(args.type, parse_ref(args.start), parse_ref(args.end), {"role": args.role})
            print("Relationship merged.")
    elif args.target == "clear":
        if not args.yes:
            sys.exit("Refusing to delete without --yes.")
        if args.which in ("vector", "all"):
            ingestion.clear_vector_store()
        if args.which in ("graph", "all"):
            neo4j_loader.clear()
        print("Cleared.")


if __name__ == "__main__":
    main()
