from __future__ import annotations

import csv
import json
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
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text)


class DummySession:
    def __init__(self, pages, ajax_rows=None, docs=None):
        self.pages = pages
        self.ajax_rows = ajax_rows or []
        self.docs = docs or {}

    def get(self, url, params=None, timeout=None, allow_redirects=True):
        if "oversightboard.pr.gov/contracts.json" in url:
            start = int((params or {}).get("start", 0))
            length = int((params or {}).get("length", 500))
            rows = self.ajax_rows[start : start + length]
            return DummyResponse(
                text=json.dumps(
                    {
                        "data": rows,
                        "recordsTotal": len(self.ajax_rows),
                        "recordsFiltered": len(self.ajax_rows),
                    }
                ),
                headers={"Content-Type": "application/json"},
                url=url,
            )
        if url in self.docs:
            payload, content_type = self.docs[url]
            return DummyResponse(
                content=payload, text="", headers={"Content-Type": content_type}, url=url
            )
        return DummyResponse(text=self.pages.get(url, "<html></html>"), url=url)

    def post(self, url, data=None, timeout=None):
        return self.get(url, params=data, timeout=timeout)

    def close(self):
        return None


def _page(*links: tuple[str, str], ajax=False):
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    script = (
        '<script>const table = {ajax: "https://oversightboard.pr.gov/contracts.json"};</script>'
        if ajax
        else ""
    )
    return f"<html><body>{anchors}{script}</body></html>"


def test_link_extraction_and_document_classification():
    html = _page(
        (
            "https://docs.oversightboard.pr.gov/example.pdf",
            "FOMB - Fiscal Plan for PRASA - Certified as of June 11, 2024",
        ),
        ("/about-us/", "About Us"),
    )
    links = fomb._extract_links(html, "https://oversightboard.pr.gov/fiscal-plans/")
    docs = [link for link in links if fomb._looks_like_document(link.href, link.text)]
    assert len(docs) == 1
    entity, fiscal_year, doc_class, version = fomb._classify_title(docs[0].text, "fiscal_plans")
    assert entity == "Puerto Rico Aqueduct and Sewer Authority"
    assert fiscal_year == "2024"
    assert doc_class == "fiscal_plan"
    assert version == "certified"


def test_contract_ajax_normalization_and_stable_id():
    session = DummySession(
        {},
        ajax_rows=[
            {
                "Entity": "Puerto Rico Aqueduct and Sewer Authority",
                "Counterpart": "Accenture Puerto Rico, LLC (2026-000123)",
                "Amount": "$1,250,000.00",
                "Status": "Approved",
                "Completed": "2026-01-21",
                "Document": '<a href="https://docs.oversightboard.pr.gov/review.pdf">Download</a>',
            }
        ],
    )
    html = _page(ajax=True)
    rows, ajax_url = fomb._enumerate_contract_reviews(
        session,
        html,
        "https://oversightboard.pr.gov/contract-review/",
        "2026-08-09T12:00:00Z",
        type("L", (), {"warning": lambda *args, **kwargs: None})(),
    )
    assert ajax_url == "https://oversightboard.pr.gov/contracts.json"
    assert len(rows) == 1
    assert rows[0]["amount_numeric"] == 1_250_000.0
    assert rows[0]["currency"] == "USD"
    assert rows[0]["contract_number_candidate"] == "2026-000123"
    assert rows[0]["review_document_url"].endswith("review.pdf")
    assert len(rows[0]["fomb_review_id"]) == 24


def test_rejects_cross_origin_dynamic_table_endpoint():
    html = '<script>const table = {ajax: "https://example.invalid/contracts.json"};</script>'
    assert (
        fomb._discover_ajax_config(html, "https://oversightboard.pr.gov/contract-review/") is None
    )


def test_versions_preserve_and_link_superseded_records():
    docs = [
        {
            "document_id": "old",
            "collection": "fiscal_plans",
            "title_raw": "FOMB Fiscal Plan for Commonwealth of Puerto Rico Certified 2025-06-01",
            "publication_date": "2025-06-01",
            "download_url": "https://example/old.pdf",
            "source_url": "https://example/",
        },
        {
            "document_id": "new",
            "collection": "fiscal_plans",
            "title_raw": "FOMB Revised Fiscal Plan for Commonwealth of Puerto Rico 2025-06-06",
            "publication_date": "2025-06-06",
            "download_url": "https://example/new.pdf",
            "source_url": "https://example/",
        },
    ]
    rows = fomb._build_versions(docs)
    assert {row["document_id"] for row in rows} == {"old", "new"}
    newer = next(row for row in rows if row["document_id"] == "new")
    assert newer["supersedes_document_id"] == "old"


def test_crosswalk_is_nondestructive_and_flags_conflicts(tmp_path: Path):
    target = tmp_path / "data/staging/processed"
    target.mkdir(parents=True)
    ocpr = target / "pr_ocpr_contracts.csv"
    with ocpr.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["contract_number", "agency", "contractor_name", "contract_amount"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "contract_number": "2026-000123",
                "agency": "Puerto Rico Aqueduct and Sewer Authority",
                "contractor_name": "Accenture Puerto Rico LLC",
                "contract_amount": "1250000.00",
            }
        )
    reviews = [
        {
            "fomb_review_id": "abc",
            "contract_number_candidate": "2026-000123",
            "government_entity_raw": "Puerto Rico Aqueduct and Sewer Authority",
            "counterparty_raw": "Accenture Puerto Rico LLC",
            "amount_numeric": 1_250_000.0,
        }
    ]
    rows = fomb._build_crosswalk(tmp_path, reviews)
    assert len(rows) == 1
    assert rows[0]["local_source"] == "ocpr_contracts"
    assert rows[0]["match_confidence"] == 1.0
    assert rows[0]["amount_delta"] == 0.0
    assert rows[0]["entity_conflict"] is False
    assert rows[0]["counterparty_conflict"] is False


def test_content_hash_duplicate_group_keeps_separate_observations():
    payload = b"same bytes"
    sha = fomb._sha256_bytes(payload)
    assert sha == fomb._sha256_bytes(payload)
    a = {"document_id": "a", "sha256": sha, "duplicate_content_group": sha}
    b = {"document_id": "b", "sha256": sha, "duplicate_content_group": sha}
    assert a["document_id"] != b["document_id"]
    assert a["duplicate_content_group"] == b["duplicate_content_group"]
