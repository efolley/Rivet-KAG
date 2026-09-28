"""Mini test suite for the LlamaIndex-based ingestion pipeline.

Builds one small sample of each supported format (md, csv, xlsx, pdf) on the fly, checks
chunking is correct for each, and exercises the /api/files upload endpoint end to end with
embedding and Milvus mocked out so the test stays fast and offline.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.ingestion.loaders import Chunk, chunk_file, chunk_text
from src.main import app

client = TestClient(app)

MARKDOWN = """# Expense Policy

Owner: People Ops.

## What can be expensed

Travel, client meals and conference tickets are reimbursed.

## Limits

Meals while travelling are capped at 60 EUR per day.
"""


def _write_pdf(path: Path, pages: list[str]) -> None:
    """Build a minimal valid PDF with one page of text per string in `pages`, using no
    dependency beyond the stdlib. Byte offsets are computed as objects are written, so this
    stays correct regardless of text length."""
    objects: list[bytes] = []
    kids = [f"{3 + i * 2} 0 R" for i in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode())
    for text in pages:
        stream = f"BT /F1 14 Tf 20 100 Td ({text}) Tj ET".encode()
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 "
            + str(3 + 2 * len(pages)).encode()
            + b" 0 R >> >> /MediaBox [0 0 300 144] /Contents "
            + str(len(objects) + 2).encode()
            + b" 0 R >>"
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref_offset}\n%%EOF".encode()
    path.write_bytes(bytes(out))


def test_markdown_chunks_one_per_heading(tmp_path: Path) -> None:
    path = tmp_path / "expense_policy.md"
    path.write_text(MARKDOWN)
    chunks = chunk_file(path)
    assert [c.heading for c in chunks] == ["Expense Policy", "What can be expensed", "Limits"]
    assert chunks[1].text == "Travel, client meals and conference tickets are reimbursed."
    assert [c.id for c in chunks] == ["expense_policy.md::0", "expense_policy.md::1", "expense_policy.md::2"]


def test_csv_chunks_one_per_row(tmp_path: Path) -> None:
    path = tmp_path / "faq.csv"
    path.write_text(
        "question,answer\nWhen is invoicing?,First business day.\nHow do I reset a password?,Use the link.\n"
    )
    chunks = chunk_file(path)
    assert len(chunks) == 2
    assert chunks[0].text == "question: When is invoicing?\nanswer: First business day."
    assert all(c.doc_type == "csv" for c in chunks)


def test_excel_chunks_one_per_row(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "expenses.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["category", "amount_eur"])
    ws.append(["Travel", 120])
    ws.append(["Meals", 45])
    wb.save(path)

    chunks = chunk_file(path)
    assert len(chunks) == 2
    assert chunks[0].text == "category: Travel, amount_eur: 120"
    assert chunks[1].text == "category: Meals, amount_eur: 45"
    assert all(c.doc_type == "xlsx" for c in chunks)


def test_pdf_chunks_one_per_page(tmp_path: Path) -> None:
    path = tmp_path / "runbook.pdf"
    _write_pdf(path, ["Incident Response Runbook", "Severity levels are SEV1 SEV2 SEV3"])
    chunks = chunk_file(path)
    assert len(chunks) == 2
    assert chunks[0].heading == "page 1"
    assert "Incident Response Runbook" in chunks[0].text
    assert "SEV1" in chunks[1].text
    assert all(c.doc_type == "pdf" for c in chunks)


def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_text("irrelevant")
    with pytest.raises(ValueError, match="Unsupported file type"):
        chunk_file(path)


def test_chunk_text_wraps_raw_text_as_one_chunk() -> None:
    chunks = chunk_text("Pets are allowed on Fridays.", source="office_note")
    assert chunks == [Chunk("office_note", "txt", 0, "", "Pets are allowed on Fridays.")]
    assert chunk_text("   ", source="empty") == []


def test_upload_endpoint_ingests_and_reports_chunk_count(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_ingest_upload(filename: str, data: bytes) -> tuple[int, str]:
        captured["filename"] = filename
        captured["data"] = data
        return 3, "md"

    monkeypatch.setattr("src.api.routes.files.ingest_upload", fake_ingest_upload)
    body = MARKDOWN.encode()
    r = client.post("/api/files", files={"file": ("policy.md", body, "text/markdown")})

    assert r.status_code == 200
    assert r.json() == {"filename": "policy.md", "doc_type": "md", "chunks_upserted": 3}
    assert captured == {"filename": "policy.md", "data": body}


def test_upload_endpoint_rejects_unsupported_type() -> None:
    r = client.post("/api/files", files={"file": ("notes.docx", b"hi", "application/octet-stream")})
    assert r.status_code == 400
    assert "Unsupported file type" in r.json()["detail"]


def test_upload_endpoint_rejects_empty_file() -> None:
    r = client.post("/api/files", files={"file": ("empty.md", b"", "text/markdown")})
    assert r.status_code == 400
    assert r.json()["detail"] == "Empty file."


def test_upload_endpoint_reports_no_extractable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.routes.files.ingest_upload", lambda filename, data: (0, "csv"))
    r = client.post("/api/files", files={"file": ("blank.csv", b"a,b\n", "text/csv")})
    assert r.status_code == 422


def test_upload_endpoint_surfaces_ingestion_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(filename: str, data: bytes) -> tuple[int, str]:
        raise ConnectionError("milvus down")

    monkeypatch.setattr("src.api.routes.files.ingest_upload", boom)
    r = client.post("/api/files", files={"file": ("policy.md", b"# Hi\n\nbody", "text/markdown")})
    assert r.status_code == 502
