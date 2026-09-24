import csv
import io
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chunk:
    source: str
    doc_type: str
    chunk_index: int
    heading: str
    text: str

    @property
    def id(self) -> str:
        return f"{self.source}::{self.chunk_index}"


def chunk_markdown(source: str, text: str) -> list[Chunk]:
    """One chunk per '## ' section; the '# ' title is used as the heading of the intro section."""
    chunks: list[Chunk] = []
    heading = ""
    body: list[str] = []

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            chunks.append(Chunk(source, "md", len(chunks), heading, content))
        body.clear()

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
        elif line.startswith("# "):
            heading = line[2:].strip()
        else:
            body.append(line)
    flush()
    return chunks


def chunk_csv(source: str, text: str) -> list[Chunk]:
    """One chunk per row, rendered as 'column: value' lines."""
    rows = csv.DictReader(io.StringIO(text))
    return [Chunk(source, "csv", i, "", "\n".join(f"{k}: {v}" for k, v in row.items())) for i, row in enumerate(rows)]


def chunk_text(source: str, text: str) -> list[Chunk]:
    return [Chunk(source, "text", 0, "", text.strip())] if text.strip() else []


def chunk_file(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return chunk_markdown(path.name, text)
    if suffix == ".csv":
        return chunk_csv(path.name, text)
    if suffix == ".txt":
        return chunk_text(path.name, text)
    raise ValueError(f"Unsupported file type: {path.name} (supported: .md, .csv, .txt)")
