"""Materialize Financial Oversight and Management Board (FOMB) public records.

Provenance-first, resumable producer for Puerto Rico FOMB public records.

Key invariants:
- discovery HTML + sanitized HTTP metadata are preserved;
- duplicate/superseded observations are never destructively discarded;
- dynamic table failure is an explicit PARTIAL state, never an empty-success;
- document downloads use persisted ETag/Last-Modified validators and SHA-256;
- interrupted document runs resume from a persisted pending-document queue;
- a failed contract-review refresh preserves the last valid normalized output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.base_downloader import HttpConfig, build_session
from scripts.config import PROJECT_ROOT, setup_logging

BASE_URL = "https://oversightboard.pr.gov/"
RAW_ROOT_REL = "data/raw/FOMB"
CHECKPOINT_REL = "data/raw/FOMB/checkpoint.json"
MANIFEST_REL = "data/manifests/fomb_documents_manifest.jsonl"
DOCUMENTS_REL = "data/staging/processed/pr_fomb_documents.csv"
CONTRACTS_REL = "data/staging/processed/pr_fomb_contract_reviews.csv"
VERSIONS_REL = "data/staging/processed/pr_fomb_fiscal_versions.csv"
CROSSWALK_REL = "data/staging/processed/pr_fomb_crosswalk.csv"

COLLECTIONS = {
    "documents": "documents/",
    "contract_review": "contract-review/",
    "fiscal_plans": "fiscal-plans/",
    "budgets": "budgets/",
    "related_documents_letters": "related-documents-and-letters/",
    "budget_reapportionments": "budget-reapportionment-requests/",
    "quarterly_financial_reports": "quarterly-financial-reports/",
    "debt": "debt/",
    "legislative_process": "legislative-process/",
    "reports": "fomb-reports/",
}
DYNAMIC_COLLECTIONS = {
    "documents",
    "contract_review",
    "budget_reapportionments",
    "quarterly_financial_reports",
}

HTTP = HttpConfig(
    user_agent="Mozilla/5.0 (compatible; MoneySweep/1.0; public-record research)",
    max_retries=3,
    base_delay_seconds=2.0,
    max_delay_seconds=20.0,
    page_sleep=0.25,
    rate_limit_sleep=60.0,
    timeout=60,
)

DOCUMENT_COLUMNS = [
    "document_id",
    "collection",
    "title_raw",
    "document_type_raw",
    "publication_date",
    "source_url",
    "download_url",
    "retrieved_at",
    "http_status",
    "content_type",
    "byte_size",
    "sha256",
    "duplicate_content_group",
    "local_path",
]
CONTRACT_COLUMNS = [
    "fomb_review_id",
    "government_entity_raw",
    "counterparty_raw",
    "amount_raw",
    "amount_numeric",
    "currency",
    "status_raw",
    "completed_date",
    "review_document_url",
    "contract_number_candidate",
    "source_url",
    "retrieved_at",
]
VERSION_COLUMNS = [
    "document_id",
    "collection",
    "covered_entity",
    "fiscal_year",
    "document_class",
    "version_label",
    "publication_date",
    "supersedes_document_id",
    "source_url",
]
CROSSWALK_COLUMNS = [
    "fomb_review_id",
    "local_source",
    "local_record_id",
    "match_basis",
    "match_confidence",
    "amount_delta",
    "date_delta_days",
    "entity_conflict",
    "counterparty_conflict",
    "status_conflict",
]

_DATE_RE = re.compile(r"\b(20\d{2})[-_/](0?[1-9]|1[0-2])[-_/]([0-2]?\d|3[01])\b")
_US_DATE_RE = re.compile(r"\b(0?[1-9]|1[0-2])[/.-]([0-2]?\d|3[01])[/.-](20\d{2})\b")
_YEAR_RE = re.compile(r"\b(?:FY\s*)?(20\d{2})\b", re.I)
_AMOUNT_RE = re.compile(r"-?\$?\s*([\d,]+(?:\.\d{1,2})?)")
_CONTRACT_RE = re.compile(r"\b20\d{2}-\d{6}(?:-[A-Z0-9]+)?\b", re.I)
_AJAX_URL_PATTERNS = [
    re.compile(r"ajax\s*:\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"sAjaxSource\s*:\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"(?:ajaxUrl|ajax_url|dataUrl|data_url)\s*[:=]\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(
        r"['\"]url['\"]\s*:\s*['\"]([^'\"]*(?:admin-ajax|wp-json|contract|document)[^'\"]*)['\"]",
        re.I,
    ),
]
_ACTION_RE = re.compile(r"['\"]?action['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", re.I)


@dataclass
class Link:
    href: str
    text: str
    context: str = ""


@dataclass
class AjaxConfig:
    url: str
    method: str = "GET"
    extra_params: dict[str, str] = field(default_factory=dict)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._href: str | None = None
        self._anchor_text: list[str] = []
        self._row_text: list[str] = []
        self._in_row = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._in_row = True
            self._row_text = []
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._in_row:
            self._row_text.append(data)
        if self._href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._anchor_text).split())
            context = " ".join("".join(self._row_text).split()) if self._in_row else ""
            self.links.append(Link(self._href, text, context))
            self._href = None
            self._anchor_text = []
        if tag == "tr":
            self._in_row = False
            self._row_text = []


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", query, ""))


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _norm_entity(value: Any) -> str:
    n = _norm(value)
    aliases = {
        "aaa": "puerto rico aqueduct and sewer authority",
        "autoridad de acueductos y alcantarillados": "puerto rico aqueduct and sewer authority",
        "prasa": "puerto rico aqueduct and sewer authority",
        "aee": "puerto rico electric power authority",
        "prepa": "puerto rico electric power authority",
        "act": "puerto rico highways and transportation authority",
        "hta": "puerto rico highways and transportation authority",
    }
    return aliases.get(n, n)


def _parse_amount(value: Any) -> float | None:
    if value is None:
        return None
    m = _AMOUNT_RE.search(str(value))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _publication_date(text: str) -> str:
    m = _DATE_RE.search(text or "")
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = _US_DATE_RE.search(text or "")
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


def _date_obj(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def _extract_links(page_html: str, page_url: str) -> list[Link]:
    parser = _LinkParser()
    parser.feed(page_html)
    seen: set[tuple[str, str, str]] = set()
    out: list[Link] = []
    for link in parser.links:
        href = _canonical_url(urljoin(page_url, html.unescape(link.href)))
        key = (href, link.text, link.context)
        if key not in seen:
            seen.add(key)
            out.append(Link(href, link.text, link.context))
    return out


def _looks_like_document(url: str, text: str) -> bool:
    lower = url.lower()
    if any(
        lower.endswith(ext) or f"{ext}?" in lower
        for ext in (".pdf", ".xlsx", ".xls", ".csv", ".doc", ".docx")
    ):
        return True
    if any(
        host in lower
        for host in ("docs.oversightboard.pr.gov", "drive.google.com", "docs.google.com")
    ):
        return True
    return "download" in _norm(text) and urlparse(url).netloc not in {"", urlparse(BASE_URL).netloc}


def _document_title(link: Link) -> str:
    anchor = " ".join((link.text or "").split())
    context = " ".join((link.context or "").split())
    if context and _norm(anchor) in {"download", "view", "view pdf", "read pdf", "read more"}:
        cleaned = re.sub(
            r"\b(download|view pdf|view|read pdf|read more)\b", " ", context, flags=re.I
        )
        cleaned = " ".join(cleaned.split())
        if cleaned:
            return cleaned
    return anchor or context or Path(urlparse(link.href).path).name


def _classify_title(title: str, collection: str) -> tuple[str, str, str, str]:
    n = _norm(title)
    entity = ""
    entity_map = {
        "commonwealth": "Commonwealth of Puerto Rico",
        "prepa": "Puerto Rico Electric Power Authority",
        "puerto rico electric power authority": "Puerto Rico Electric Power Authority",
        "prasa": "Puerto Rico Aqueduct and Sewer Authority",
        "puerto rico aqueduct": "Puerto Rico Aqueduct and Sewer Authority",
        "university of puerto rico": "University of Puerto Rico",
        "upr": "University of Puerto Rico",
        "highway and transportation authority": "Puerto Rico Highways and Transportation Authority",
        "hta": "Puerto Rico Highways and Transportation Authority",
        "pridco": "Puerto Rico Industrial Development Company",
        "crim": "Municipal Revenue Collections Center",
        "cofina": "Puerto Rico Sales Tax Financing Corporation",
        "cossec": "Public Corporation for Supervision and Insurance of Cooperatives",
        "gdb": "Government Development Bank for Puerto Rico",
    }
    for needle, canonical in entity_map.items():
        if needle in n:
            entity = canonical
            break
    year_m = _YEAR_RE.search(title or "")
    fiscal_year = year_m.group(1) if year_m else ""
    if "fiscal plan" in n:
        doc_class = "fiscal_plan"
    elif "budget" in n and "reapportion" not in n and "reprogram" not in n:
        doc_class = "budget"
    elif "reapportion" in n or "reprogram" in n:
        doc_class = "budget_reapportionment"
    elif "quarterly" in n and "report" in n:
        doc_class = "quarterly_financial_report"
    elif collection == "contract_review":
        doc_class = "contract_review"
    elif collection == "legislative_process":
        doc_class = "legislative_review"
    elif collection == "debt":
        doc_class = "debt"
    else:
        doc_class = collection
    version = (
        "revised" if "revised" in n or "amended" in n else "certified" if "certified" in n else ""
    )
    return entity, fiscal_year, doc_class, version


def _discover_ajax_config(page_html: str, page_url: str) -> AjaxConfig | None:
    decoded = html.unescape(page_html).replace("\\/", "/")
    candidates: list[str] = []
    for pattern in _AJAX_URL_PATTERNS:
        candidates.extend(pattern.findall(decoded))
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or "{{" in candidate or "<%" in candidate:
            continue
        url = urljoin(page_url, candidate)
        parsed = urlparse(url)
        page = urlparse(page_url)
        if parsed.scheme != "https" or parsed.netloc.lower() != page.netloc.lower():
            continue
        extra: dict[str, str] = {}
        if "admin-ajax" in url:
            actions = [
                a
                for a in _ACTION_RE.findall(decoded)
                if "contract" in a.lower() or "document" in a.lower()
            ]
            if len(set(actions)) == 1:
                extra["action"] = actions[0]
        method = (
            "POST" if re.search(r"(?:type|method)\s*:\s*['\"]POST['\"]", decoded, re.I) else "GET"
        )
        return AjaxConfig(url=url, method=method, extra_params=extra)
    return None


def _discover_ajax_url(page_html: str, page_url: str) -> str | None:
    cfg = _discover_ajax_config(page_html, page_url)
    return cfg.url if cfg else None


def _json_rows(payload: Any) -> tuple[list[Any], int | None]:
    if isinstance(payload, list):
        return payload, len(payload)
    if not isinstance(payload, dict):
        return [], None
    for key in ("data", "rows", "results", "aaData"):
        rows = payload.get(key)
        if isinstance(rows, list):
            total = (
                payload.get("recordsFiltered")
                or payload.get("recordsTotal")
                or payload.get("total")
            )
            try:
                total = int(total) if total is not None else None
            except (TypeError, ValueError):
                total = None
            return rows, total
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _json_rows(nested)
    return [], None


def _row_value(row: Any, *keys: str) -> str:
    if isinstance(row, dict):
        normalized = {_norm(k).replace(" ", ""): v for k, v in row.items()}
        for key in keys:
            value = normalized.get(_norm(key).replace(" ", ""))
            if value not in (None, ""):
                return str(value).strip()
    if isinstance(row, list):
        positions = {
            "entity": 0,
            "counterpart": 1,
            "amount": 2,
            "status": 3,
            "completed": 4,
            "document": 5,
        }
        for key in keys:
            normalized_key = _norm(key).replace(" ", "")
            idx = positions.get(normalized_key)
            if idx is not None and idx < len(row):
                raw = str(row[idx]).strip()
                if normalized_key in {"document", "download", "url"}:
                    return raw
                return re.sub(r"<[^>]+>", "", raw).strip()
    return ""


def _document_href_from_value(value: str, page_url: str) -> str:
    m = re.search(r"href=['\"]([^'\"]+)['\"]", value or "", re.I)
    if m:
        return _canonical_url(urljoin(page_url, html.unescape(m.group(1))))
    if str(value).startswith(("http://", "https://")):
        return _canonical_url(str(value))
    return ""


def _ajax_request(
    session: requests.Session, cfg: AjaxConfig, params: dict[str, Any]
) -> requests.Response:
    payload = {**cfg.extra_params, **params}
    methods = [cfg.method.upper(), "POST" if cfg.method.upper() == "GET" else "GET"]
    last: requests.Response | None = None
    for method in methods:
        if method == "POST":
            response = session.post(cfg.url, data=payload, timeout=HTTP.timeout)
        else:
            response = session.get(cfg.url, params=payload, timeout=HTTP.timeout)
        last = response
        if response.status_code not in (400, 404, 405):
            return response
    assert last is not None
    return last


def _enumerate_contract_reviews(
    session: requests.Session, page_html: str, page_url: str, retrieved_at: str, logger
) -> tuple[list[dict[str, Any]], str | None]:
    cfg = _discover_ajax_config(page_html, page_url)
    if not cfg:
        return [], None
    records: list[dict[str, Any]] = []
    start, length = 0, 500
    while True:
        try:
            response = _ajax_request(session, cfg, {"draw": 1, "start": start, "length": length})
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            logger.warning("FOMB contract AJAX enumeration stopped at start=%s: %s", start, exc)
            break
        rows, total = _json_rows(payload)
        if not rows:
            break
        for raw in rows:
            entity = _row_value(raw, "entity", "government entity", "agency")
            counterpart = _row_value(raw, "counterpart", "counterparty", "contractor")
            amount_raw = _row_value(raw, "amount")
            status = _row_value(raw, "status")
            completed = _row_value(raw, "completed", "completed date", "date")
            document_value = _row_value(raw, "document", "download", "url")
            review_document_url = _document_href_from_value(document_value, page_url)
            stable = "|".join(
                [_norm(entity), _norm(counterpart), amount_raw, completed, review_document_url]
            )
            contract_m = _CONTRACT_RE.search(" ".join([counterpart, document_value]))
            records.append(
                {
                    "fomb_review_id": hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24],
                    "government_entity_raw": entity,
                    "counterparty_raw": counterpart,
                    "amount_raw": amount_raw,
                    "amount_numeric": _parse_amount(amount_raw),
                    "currency": "USD" if amount_raw else "",
                    "status_raw": status,
                    "completed_date": _publication_date(completed),
                    "review_document_url": review_document_url,
                    "contract_number_candidate": contract_m.group(0).upper() if contract_m else "",
                    "source_url": page_url,
                    "retrieved_at": retrieved_at,
                }
            )
        start += len(rows)
        if len(rows) < length or (total is not None and start >= total):
            break
    return records, cfg.url


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {key: "" if row.get(key) is None else row.get(key) for key in columns}
                )
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error, UnicodeError):
        return []


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "fomb_checkpoint_v1",
            "collections": {},
            "documents": {},
            "pending_document_ids": [],
            "contract_review": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("checkpoint not an object")
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "schema_version": "fomb_checkpoint_v1",
            "collections": {},
            "documents": {},
            "pending_document_ids": [],
            "contract_review": {},
        }
    data.setdefault("schema_version", "fomb_checkpoint_v1")
    data.setdefault("collections", {})
    data.setdefault("documents", {})
    data.setdefault("pending_document_ids", [])
    data.setdefault("contract_review", {})
    return data


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("document_id"):
                    out[str(row["document_id"])] = row
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return out


def _build_crosswalk(root: Path, reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        ("ocpr_contracts", root / "data/staging/processed/pr_ocpr_contracts.csv"),
        ("transition_contracts", root / "data/staging/processed/pr_transition_contracts.csv"),
        ("act_transition", root / "data/staging/processed/pr_act_transition_contracts.csv"),
        ("acuden_transition", root / "data/staging/processed/pr_acuden_transition_contracts.csv"),
    ]
    output: list[dict[str, Any]] = []
    for source_name, path in candidates:
        for local in _load_csv(path):
            local_contract = str(
                local.get("contract_number") or local.get("contract_id") or ""
            ).strip()
            local_entity = str(
                local.get("agency") or local.get("entity") or local.get("government_entity") or ""
            )
            local_counterparty = str(
                local.get("contractor_name")
                or local.get("contractor")
                or local.get("counterparty")
                or ""
            )
            local_amount = _parse_amount(local.get("contract_amount") or local.get("amount"))
            local_date = _publication_date(
                str(
                    local.get("grant_date")
                    or local.get("date_of_grant")
                    or local.get("start_date")
                    or ""
                )
            )
            for review in reviews:
                basis: list[str] = []
                score = 0.0
                contract_exact = bool(
                    review.get("contract_number_candidate")
                    and local_contract
                    and _norm(review["contract_number_candidate"]) == _norm(local_contract)
                )
                entity_exact = bool(
                    _norm_entity(review.get("government_entity_raw"))
                    and _norm_entity(review.get("government_entity_raw"))
                    == _norm_entity(local_entity)
                )
                counterpart_exact = bool(
                    _norm(review.get("counterparty_raw"))
                    and _norm(review.get("counterparty_raw")) == _norm(local_counterparty)
                )
                if contract_exact:
                    basis.append("contract_number")
                    score += 0.75
                if entity_exact:
                    basis.append("entity_exact")
                    score += 0.15
                if counterpart_exact:
                    basis.append("counterparty_exact")
                    score += 0.25
                f_amount = review.get("amount_numeric")
                amount_delta = None
                if f_amount is not None and local_amount is not None:
                    amount_delta = round(float(f_amount) - float(local_amount), 2)
                    tolerance = max(1.0, abs(float(f_amount)) * 0.001)
                    if abs(amount_delta) <= tolerance:
                        basis.append("amount_close")
                        score += 0.10
                # Without a contract number, require the entity+counterparty pair.
                if not contract_exact and not (entity_exact and counterpart_exact):
                    continue
                if score < 0.40:
                    continue
                review_date = _date_obj(str(review.get("completed_date") or ""))
                source_date = _date_obj(local_date)
                date_delta = (review_date - source_date).days if review_date and source_date else ""
                output.append(
                    {
                        "fomb_review_id": review["fomb_review_id"],
                        "local_source": source_name,
                        "local_record_id": local_contract
                        or hashlib.sha256(json.dumps(local, sort_keys=True).encode()).hexdigest()[
                            :20
                        ],
                        "match_basis": ";".join(basis),
                        "match_confidence": min(round(score, 3), 1.0),
                        "amount_delta": "" if amount_delta is None else amount_delta,
                        "date_delta_days": date_delta,
                        "entity_conflict": bool(
                            local_entity
                            and review.get("government_entity_raw")
                            and not entity_exact
                        ),
                        "counterparty_conflict": bool(
                            local_counterparty
                            and review.get("counterparty_raw")
                            and not counterpart_exact
                        ),
                        "status_conflict": False,
                    }
                )
    output.sort(
        key=lambda row: (
            -float(row["match_confidence"]),
            row["fomb_review_id"],
            row["local_source"],
            row["local_record_id"],
        )
    )
    return output


def _build_versions(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in documents:
        entity, fiscal_year, doc_class, version = _classify_title(
            doc.get("title_raw", ""), doc.get("collection", "")
        )
        if doc_class not in {"fiscal_plan", "budget", "budget_reapportionment"}:
            continue
        rows.append(
            {
                "document_id": doc["document_id"],
                "collection": doc["collection"],
                "covered_entity": entity,
                "fiscal_year": fiscal_year,
                "document_class": doc_class,
                "version_label": version,
                "publication_date": doc.get("publication_date", ""),
                "supersedes_document_id": "",
                "source_url": doc.get("download_url") or doc.get("source_url"),
            }
        )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(
            (row["covered_entity"], row["fiscal_year"], row["document_class"]), []
        ).append(row)
    for group in grouped.values():
        group.sort(key=lambda r: (r["publication_date"], r["document_id"]))
        previous = ""
        for row in group:
            if previous and row["version_label"] in {"revised", "certified"}:
                row["supersedes_document_id"] = previous
            previous = row["document_id"]
    return sorted(
        rows,
        key=lambda r: (
            r["covered_entity"],
            r["fiscal_year"],
            r["document_class"],
            r["publication_date"],
            r["document_id"],
        ),
    )


def _extension_for(content_type: str, url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix and len(suffix) <= 8:
        return suffix
    return {
        "application/pdf": ".pdf",
        "text/csv": ".csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel": ".xls",
    }.get((content_type or "").split(";")[0].strip().lower(), ".bin")


def _conditional_headers(entry: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    if entry.get("etag"):
        headers["If-None-Match"] = str(entry["etag"])
    if entry.get("last_modified"):
        headers["If-Modified-Since"] = str(entry["last_modified"])
    return headers


def _merge_prior_document(doc: dict[str, Any], prior: dict[str, Any] | None, root: Path) -> None:
    if not prior:
        return
    local = str(prior.get("local_path") or "")
    if local and not (root / local).exists():
        return
    for key in (
        "http_status",
        "content_type",
        "byte_size",
        "sha256",
        "duplicate_content_group",
        "local_path",
    ):
        if prior.get(key) not in (None, ""):
            doc[key] = prior[key]


def run(
    root: Path | str | None = None,
    download_documents: bool = True,
    max_documents: int | None = None,
) -> dict[str, Any]:
    root = Path(root) if root is not None else PROJECT_ROOT
    logger = setup_logging("download_fomb")
    raw_root = root / RAW_ROOT_REL
    discovery_dir = raw_root / "discovery"
    content_dir = raw_root / "documents"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = root / CHECKPOINT_REL
    checkpoint = _load_checkpoint(checkpoint_path)
    prior_manifest = _load_manifest(root / MANIFEST_REL)
    retrieved_at = _utc_now()
    session = build_session(HTTP.user_agent)

    documents: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    errors: list[str] = []
    collection_state: dict[str, Any] = {}
    contract_refresh_ok = False

    for collection, rel in COLLECTIONS.items():
        page_url = urljoin(BASE_URL, rel)
        cached = checkpoint["collections"].get(collection, {})
        headers = _conditional_headers(cached)
        try:
            response = session.get(page_url, headers=headers, timeout=HTTP.timeout)
            if response.status_code == 304:
                html_path = discovery_dir / f"{collection}.html"
                if not html_path.exists():
                    response = session.get(page_url, timeout=HTTP.timeout)
                else:
                    page_html = html_path.read_text(encoding="utf-8", errors="replace")
                    body = html_path.read_bytes()
                    status_code = 304
            if response.status_code != 304:
                response.raise_for_status()
                body = response.content
                page_html = response.text
                status_code = response.status_code
                (discovery_dir / f"{collection}.html").write_bytes(body)
            checkpoint["collections"][collection] = {
                "source_url": page_url,
                "etag": response.headers.get("ETag") or cached.get("etag", ""),
                "last_modified": response.headers.get("Last-Modified")
                or cached.get("last_modified", ""),
                "sha256": _sha256_bytes(body),
                "byte_size": len(body),
                "last_checked_at": retrieved_at,
            }
            headers_payload = {
                "source_url": page_url,
                "retrieved_at": retrieved_at,
                "status_code": status_code,
                "headers": {
                    k: v for k, v in response.headers.items() if k.lower() not in {"set-cookie"}
                },
                "sha256": _sha256_bytes(body),
                "byte_size": len(body),
            }
            _atomic_write_json(discovery_dir / f"{collection}.headers.json", headers_payload)
            _atomic_write_json(checkpoint_path, checkpoint)
        except (requests.RequestException, OSError) as exc:
            errors.append(f"{collection}: {exc}")
            collection_state[collection] = {"status": "ERROR", "source_url": page_url}
            continue

        links = _extract_links(page_html, page_url)
        doc_links = [link for link in links if _looks_like_document(link.href, link.text)]
        for link in doc_links:
            title = _document_title(link)
            stable = f"{collection}|{_canonical_url(link.href)}|{title}"
            document_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
            doc = {
                "document_id": document_id,
                "collection": collection,
                "title_raw": title,
                "document_type_raw": _classify_title(title, collection)[2],
                "publication_date": _publication_date(title or link.context),
                "source_url": page_url,
                "download_url": link.href,
                "retrieved_at": retrieved_at,
                "http_status": "",
                "content_type": "",
                "byte_size": "",
                "sha256": "",
                "duplicate_content_group": "",
                "local_path": "",
            }
            _merge_prior_document(doc, prior_manifest.get(document_id), root)
            documents.append(doc)

        state: dict[str, Any] = {
            "status": "OK",
            "source_url": page_url,
            "http_status": status_code,
            "static_document_links": len(doc_links),
        }
        cfg = _discover_ajax_config(page_html, page_url)
        if cfg:
            state["ajax_url"] = cfg.url
            state["ajax_method"] = cfg.method
        if collection == "contract_review":
            contract_rows, ajax_url = _enumerate_contract_reviews(
                session, page_html, page_url, retrieved_at, logger
            )
            if contract_rows:
                reviews.extend(contract_rows)
                contract_refresh_ok = True
                checkpoint["contract_review"] = {
                    "ajax_url": ajax_url or "",
                    "last_success_at": retrieved_at,
                    "row_count": len(contract_rows),
                }
                _atomic_write_json(checkpoint_path, checkpoint)
            state["contract_rows"] = len(contract_rows)
            if not ajax_url:
                state["status"] = "PARTIAL_DYNAMIC_ENDPOINT_UNDISCOVERED"
                errors.append(
                    "contract_review: dynamic table endpoint not discovered; raw HTML preserved"
                )
            elif not contract_rows:
                state["status"] = "PARTIAL_DYNAMIC_ENUMERATION_EMPTY"
                errors.append(
                    "contract_review: dynamic endpoint discovered but no rows materialized; previous normalized output preserved"
                )
        elif collection in DYNAMIC_COLLECTIONS and not doc_links and not cfg:
            state["status"] = "PARTIAL_DYNAMIC_ENDPOINT_UNDISCOVERED"
            errors.append(
                f"{collection}: dynamic table endpoint not discovered; raw HTML preserved"
            )
        collection_state[collection] = state

    unique_docs: dict[str, dict[str, Any]] = {doc["document_id"]: doc for doc in documents}
    documents = sorted(
        unique_docs.values(),
        key=lambda d: (d["collection"], d["publication_date"], d["title_raw"], d["download_url"]),
    )

    # Resume interrupted queues first, then append newly discovered observations.
    pending_ids = [str(x) for x in checkpoint.get("pending_document_ids", [])]
    order = {doc["document_id"]: doc for doc in documents}
    queued = [order[x] for x in pending_ids if x in order]
    queued_ids = {d["document_id"] for d in queued}
    queued.extend(d for d in documents if d["document_id"] not in queued_ids)
    documents_to_fetch = queued if max_documents is None else queued[: max(0, max_documents)]

    if download_documents:
        checkpoint["pending_document_ids"] = [d["document_id"] for d in documents_to_fetch]
        _atomic_write_json(checkpoint_path, checkpoint)
        for idx, doc in enumerate(documents_to_fetch, 1):
            observed_url = _canonical_url(doc["download_url"])
            cached = checkpoint["documents"].get(observed_url, {})
            req_headers = _conditional_headers(cached)
            try:
                response = session.get(
                    doc["download_url"],
                    headers=req_headers,
                    timeout=HTTP.timeout,
                    allow_redirects=True,
                )
                if response.status_code == 304:
                    local_path = str(cached.get("local_path") or "")
                    if not local_path or not (root / local_path).exists():
                        response = session.get(
                            doc["download_url"], timeout=HTTP.timeout, allow_redirects=True
                        )
                    else:
                        not_modified_metadata: dict[str, Any] = {
                            "download_url": cached.get("resolved_url") or observed_url,
                            "http_status": 304,
                            "content_type": cached.get("content_type", ""),
                            "byte_size": cached.get("byte_size", ""),
                            "sha256": cached.get("sha256", ""),
                            "duplicate_content_group": cached.get("sha256", ""),
                            "local_path": local_path,
                        }
                        doc.update(not_modified_metadata)
                if response.status_code != 304:
                    response.raise_for_status()
                    payload = response.content
                    sha = _sha256_bytes(payload)
                    content_type = response.headers.get("Content-Type", "")
                    ext = _extension_for(content_type, response.url)
                    local = content_dir / f"{sha}{ext}"
                    if not local.exists():
                        local.write_bytes(payload)
                    downloaded_metadata: dict[str, Any] = {
                        "download_url": _canonical_url(response.url),
                        "http_status": response.status_code,
                        "content_type": content_type,
                        "byte_size": len(payload),
                        "sha256": sha,
                        "duplicate_content_group": sha,
                        "local_path": str(local.relative_to(root)),
                    }
                    doc.update(downloaded_metadata)
                checkpoint["documents"][observed_url] = {
                    "resolved_url": doc["download_url"],
                    "etag": response.headers.get("ETag") or cached.get("etag", ""),
                    "last_modified": response.headers.get("Last-Modified")
                    or cached.get("last_modified", ""),
                    "sha256": doc.get("sha256", ""),
                    "local_path": doc.get("local_path", ""),
                    "content_type": doc.get("content_type", ""),
                    "byte_size": doc.get("byte_size", ""),
                    "last_checked_at": retrieved_at,
                }
                checkpoint["pending_document_ids"] = [
                    x for x in checkpoint["pending_document_ids"] if x != doc["document_id"]
                ]
                _atomic_write_json(checkpoint_path, checkpoint)
            except (requests.RequestException, OSError) as exc:
                errors.append(f"document {doc['download_url']}: {exc}")
            if idx % 100 == 0:
                logger.info("Checked %s/%s FOMB documents", idx, len(documents_to_fetch))

    manifest_path = root / MANIFEST_REL
    _atomic_write_text(
        manifest_path,
        "".join(json.dumps(doc, sort_keys=True, ensure_ascii=False) + "\n" for doc in documents),
    )
    _write_csv(root / DOCUMENTS_REL, documents, DOCUMENT_COLUMNS)

    if contract_refresh_ok:
        review_by_id = {row["fomb_review_id"]: row for row in reviews}
        reviews = sorted(
            review_by_id.values(),
            key=lambda r: (
                r["completed_date"],
                r["government_entity_raw"],
                r["counterparty_raw"],
                r["fomb_review_id"],
            ),
        )
        _write_csv(root / CONTRACTS_REL, reviews, CONTRACT_COLUMNS)
    else:
        reviews = _load_csv(root / CONTRACTS_REL)

    versions = _build_versions(documents)
    _write_csv(root / VERSIONS_REL, versions, VERSION_COLUMNS)
    crosswalk = _build_crosswalk(root, reviews)
    _write_csv(root / CROSSWALK_REL, crosswalk, CROSSWALK_COLUMNS)

    state_path = raw_root / "collection_state.json"
    _atomic_write_json(
        state_path,
        {
            "retrieved_at": retrieved_at,
            "collections": collection_state,
            "errors": errors,
            "checkpoint": {"pending_documents": len(checkpoint.get("pending_document_ids", []))},
        },
    )
    session.close()
    return {
        "rows": len(documents),
        "documents": len(documents),
        "contract_reviews": len(reviews),
        "versions": len(versions),
        "crosswalks": len(crosswalk),
        "pending_documents": len(checkpoint.get("pending_document_ids", [])),
        "path": str(root / DOCUMENTS_REL),
        "errors": errors,
        "status": "OK" if not errors else "PARTIAL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--no-download-documents", action="store_true")
    parser.add_argument("--max-documents", type=int)
    args = parser.parse_args(argv)
    result = run(
        root=args.root,
        download_documents=not args.no_download_documents,
        max_documents=args.max_documents,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["documents"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
