"""Turn a file into text chunks ready to embed.

CSV, Excel and PDF go through LlamaIndex readers, configured to produce one chunk per row (CSV,
Excel) or per page (PDF). Markdown is split directly on '##' headings: LlamaIndex's own
MarkdownReader only starts a new chunk when a heading *level* repeats, which merges a
document's first section into its title instead of giving one chunk per heading.
"""

from dataclasses import dataclass
from pathlib import Path

from llama_index.readers.file import PagedCSVReader, PandasExcelReader, PDFReader

DOC_TYPES = {
    ".md": "md",
    ".markdown": "md",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".pdf": "pdf",
    ".txt": "txt",
}
SUPPORTED_SUFFIXES = set(DOC_TYPES)


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


def _markdown_chunks(path: Path, name: str) -> list[Chunk]:
    """One chunk per '## ' section; the '# ' title becomes the heading of the intro section."""
    heading = ""
    body: list[str] = []
    chunks: list[Chunk] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            chunks.append(Chunk(name, "md", len(chunks), heading, text))
        body.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
        elif line.startswith("# "):
            heading = line[2:].strip()
        else:
            body.append(line)
    flush()
    return chunks


def _csv_chunks(path: Path, name: str) -> list[Chunk]:
    rows = PagedCSVReader().load_data(path)
    return [Chunk(name, "csv", i, "", d.text.strip()) for i, d in enumerate(rows) if d.text.strip()]


def _excel_chunks(path: Path, name: str) -> list[Chunk]:
    rows = PandasExcelReader(concat_rows=False).load_data(path)
    return [Chunk(name, "xlsx", i, "", d.text.strip()) for i, d in enumerate(rows) if d.text.strip()]


def _pdf_chunks(path: Path, name: str) -> list[Chunk]:
    pages = PDFReader().load_data(path)
    chunks: list[Chunk] = []
    for i, d in enumerate(pages):
        text = d.text.strip()
        if text:
            label = d.metadata.get("page_label", str(i + 1))
            chunks.append(Chunk(name, "pdf", len(chunks), f"page {label}", text))
    return chunks


def _text_chunks(path: Path, name: str) -> list[Chunk]:
    text = path.read_text(encoding="utf-8").strip()
    return [Chunk(name, "txt", 0, "", text)] if text else []


def chunk_text(text: str, source: str) -> list[Chunk]:
    """Wrap a piece of raw text (not read from a file) as a single chunk."""
    text = text.strip()
    return [Chunk(source, "txt", 0, "", text)] if text else []


def chunk_file(path: Path, source: str | None = None) -> list[Chunk]:
    """Chunk a file on disk. `source` overrides the filename shown in the result (e.g. for uploads
    written to a temp path)."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {path.name!r} (supported: {', '.join(sorted(SUPPORTED_SUFFIXES))})")
    name = source or path.name
    if suffix in {".md", ".markdown"}:
        return _markdown_chunks(path, name)
    if suffix == ".csv":
        return _csv_chunks(path, name)
    if suffix in {".xlsx", ".xls"}:
        return _excel_chunks(path, name)
    if suffix == ".pdf":
        return _pdf_chunks(path, name)
    return _text_chunks(path, name)
