from __future__ import annotations

import csv
from pathlib import Path

from scripts import download_fomb as fomb


class DummyResponse:
    def __init__(
        self,
        *,
        text="",
        content=None,
        status_code=200,
        headers=None,
        url="https://oversightboard.pr.gov/",
    ):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html"}
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 304:
            raise RuntimeError(f"HTTP {self.status_code}")


class ConditionalSession:
    def __init__(self, page_html: str, document_url: str):
        self.page_html = page_html
        self.document_url = document_url
        self.document_gets = 0
        self.conditional_headers = []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
        headers = headers or {}
        if url == "https://oversightboard.pr.gov/fiscal-plans/":
            return DummyResponse(
                text=self.page_html,
                headers={"Content-Type": "text/html", "ETag": '"page-v1"'},
                url=url,
            )
        if url == self.document_url:
            self.document_gets += 1
            self.conditional_headers.append(dict(headers))
            if headers.get("If-None-Match") == '"doc-v1"':
                return DummyResponse(
                    status_code=304,
                    headers={"ETag": '"doc-v1"', "Content-Type": "application/pdf"},
                    url=url,
                )
            return DummyResponse(
                content=b"PDF-BYTES-V1",
                headers={"ETag": '"doc-v1"', "Content-Type": "application/pdf"},
                url=url,
            )
        return DummyResponse(text="<html></html>", url=url)

    def post(self, url, data=None, timeout=None):
        return self.get(url, params=data, timeout=timeout)

    def close(self):
        return None


def test_download_anchor_inherits_table_row_title():
    page = """
    <table><tr><td>FOMB - PRASA - Certified Fiscal Plan FY2025</td>
    <td>2025-06-10</td><td><a href="https://docs.oversightboard.pr.gov/prasa.pdf">Download</a></td></tr></table>
    """
    links = fomb._extract_links(page, "https://oversightboard.pr.gov/fiscal-plans/")
    doc = next(link for link in links if fomb._looks_like_document(link.href, link.text))
    title = fomb._document_title(doc)
    assert "PRASA" in title
    assert "Certified Fiscal Plan" in title
    assert title != "Download"


def test_conditional_document_refresh_reuses_content_addressed_bytes(tmp_path: Path, monkeypatch):
    document_url = "https://docs.oversightboard.pr.gov/prasa-fy2025.pdf"
    page = f"""
    <table><tr><td>FOMB - PRASA - Certified Fiscal Plan FY2025 2025-06-10</td>
    <td><a href="{document_url}">Download</a></td></tr></table>
    """
    monkeypatch.setattr(fomb, "COLLECTIONS", {"fiscal_plans": "fiscal-plans/"})
    monkeypatch.setattr(fomb, "DYNAMIC_COLLECTIONS", set())

    first = ConditionalSession(page, document_url)
    monkeypatch.setattr(fomb, "build_session", lambda _ua: first)
    result1 = fomb.run(root=tmp_path, download_documents=True)
    assert result1["status"] == "OK"
    assert result1["pending_documents"] == 0
    assert first.document_gets == 1

    raw_docs = list((tmp_path / "data/raw/FOMB/documents").glob("*"))
    assert len(raw_docs) == 1
    original_bytes = raw_docs[0].read_bytes()

    second = ConditionalSession(page, document_url)
    monkeypatch.setattr(fomb, "build_session", lambda _ua: second)
    result2 = fomb.run(root=tmp_path, download_documents=True)
    assert result2["pending_documents"] == 0
    assert second.document_gets == 1
    assert second.conditional_headers[-1].get("If-None-Match") == '"doc-v1"'
    assert raw_docs[0].read_bytes() == original_bytes
    assert len(list((tmp_path / "data/raw/FOMB/documents").glob("*"))) == 1


def test_failed_contract_dynamic_refresh_preserves_previous_csv(tmp_path: Path, monkeypatch):
    processed = tmp_path / "data/staging/processed"
    processed.mkdir(parents=True)
    contracts = processed / "pr_fomb_contract_reviews.csv"
    with contracts.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fomb.CONTRACT_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "fomb_review_id": "prior-review",
                "government_entity_raw": "Puerto Rico Aqueduct and Sewer Authority",
                "counterparty_raw": "Example Contractor LLC",
                "amount_raw": "$100.00",
                "amount_numeric": "100.0",
                "currency": "USD",
                "status_raw": "Approved",
                "completed_date": "2025-01-01",
                "review_document_url": "https://example.invalid/review.pdf",
                "contract_number_candidate": "",
                "source_url": "https://oversightboard.pr.gov/contract-review/",
                "retrieved_at": "2025-01-01T00:00:00Z",
            }
        )

    class ShellSession:
        def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
            return DummyResponse(
                text="<html><table><tr><th>Entity</th><th>Counterpart</th></tr></table></html>",
                url=url,
            )

        def post(self, url, data=None, timeout=None):
            return self.get(url, params=data, timeout=timeout)

        def close(self):
            return None

    monkeypatch.setattr(fomb, "COLLECTIONS", {"contract_review": "contract-review/"})
    monkeypatch.setattr(fomb, "DYNAMIC_COLLECTIONS", {"contract_review"})
    monkeypatch.setattr(fomb, "build_session", lambda _ua: ShellSession())
    result = fomb.run(root=tmp_path, download_documents=False)
    assert result["contract_reviews"] == 1
    assert any("dynamic table endpoint not discovered" in error for error in result["errors"])
    with contracts.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [row["fomb_review_id"] for row in rows] == ["prior-review"]
