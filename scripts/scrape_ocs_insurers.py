"""Materialize the OCS domestic-insurer list and annual financial-report index.

The two surfaces are kept separate because a current insurer listing and a
historical annual-report observation are different facts. Raw display names are
preserved exactly; this producer does not collapse aliases across years.

When ``GUIDE_SOURCE_SNAPSHOT_DIR`` is set, both authoritative HTTP responses are
frozen byte-for-byte under a unique UTC run directory. The manifest records URL,
retrieval UTC, response metadata, byte size, SHA256, schema fingerprints, and
processed-output counts/hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests
from lxml import html as lxml_html

from moneysweep.runtime.base_downloader import HttpConfig, build_session, file_has_data
from moneysweep.runtime.post_ingest import apply_post_ingest
from scripts.config import PROJECT_ROOT, setup_logging

SOURCE_ID = "ocs_insurer_registry"
INSURERS_URL = "https://www.ocs.pr.gov/consumidores/aseguradores-del-pais"
ANNUAL_URL = "https://www.ocs.pr.gov/regulados/informes-anuales"
INSURERS_OUT_REL = "data/staging/processed/pr_ocs_insurers.csv"
ANNUAL_OUT_REL = "data/staging/processed/pr_ocs_insurer_annual_reports.csv"

HTTP = HttpConfig(
    user_agent="Mozilla/5.0 (compatible; MoneySweep/1.0; PR public-money research)",
    max_retries=3,
    base_delay_seconds=2.0,
    max_delay_seconds=12.0,
    page_sleep=0.25,
    rate_limit_sleep=30.0,
    timeout=30,
)

INSURER_COLUMNS = [
    "source_record_id",
    "insurer_name_raw",
    "website_raw",
    "source_url",
    "retrieved_at_utc",
]
ANNUAL_COLUMNS = [
    "source_record_id",
    "report_year_raw",
    "insurer_name_raw",
    "report_url",
    "source_url",
    "retrieved_at_utc",
]
_YEAR_RE = re.compile(r"^(20\d{2})$")
_YEAR_ANY_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _sid(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _schema_fingerprint(columns: list[str]) -> str:
    return hashlib.sha256("\x1f".join(columns).encode("utf-8")).hexdigest()


def _external_links(node) -> list[str]:
    links = [str(x).strip() for x in node.xpath(".//a[@href]/@href")]
    return [
        x
        for x in links
        if x.startswith("http")
        and "ocs.pr.gov" not in x.casefold()
        and "oig.pr.gov" not in x.casefold()
        and "prits.pr.gov" not in x.casefold()
        and "googletagmanager.com" not in x.casefold()
    ]


def _card_display_name(img) -> tuple[str, str]:
    """Return smallest-card visible display text and website.

    The live OCS page commonly uses short brand names in ``img alt`` while the
    visible card text contains the insurer/legal display name. Prefer visible
    non-link text when present; retain the image alt only as a fixture/fallback.
    """
    alt = _clean(img.get("alt") or "")
    parent = img
    for _ in range(7):
        if parent is None:
            break
        external = _external_links(parent)
        if external:
            texts = [
                _clean(str(x))
                for x in parent.xpath(".//text()[not(ancestor::a)]")
                if _clean(str(x))
            ]
            unique_texts: list[str] = []
            for text in texts:
                if text not in unique_texts:
                    unique_texts.append(text)
            visible = " ".join(unique_texts).strip()
            if visible and len(visible) <= 500:
                return visible, external[0]
            if alt:
                return alt, external[0]
        parent = parent.getparent()
    return alt, ""


def parse_insurers(page_html: str, *, source_url: str, retrieved_at: str) -> list[dict]:
    """Extract OCS insurer cards without collapsing card text into legal identities."""
    doc = lxml_html.fromstring(page_html)
    rows: list[dict] = []
    seen_exact: set[tuple[str, str]] = set()
    excluded_alt = {
        "image",
        "ocs",
        "logo",
        "gobierno de puerto rico",
        "sello ogp",
    }

    for img in doc.xpath("//img[@alt]"):
        alt = _clean(img.get("alt") or "")
        if not alt or alt.casefold() in excluded_alt:
            continue
        name, website = _card_display_name(img)
        name = _clean(name)
        if not name:
            continue
        key = (name, website)
        if key in seen_exact:
            continue
        seen_exact.add(key)
        rows.append(
            {
                "source_record_id": _sid("current", name, website),
                "insurer_name_raw": name,
                "website_raw": website,
                "source_url": source_url,
                "retrieved_at_utc": retrieved_at,
            }
        )

    if not rows:
        raise RuntimeError("OCS insurer parser found zero insurer cards")
    return rows


def _nearest_year(node) -> str:
    preceding = node.xpath(
        "preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::div or self::span]"
    )
    for cand in reversed(preceding):
        text = _clean(cand.text_content())
        match = _YEAR_RE.match(text)
        if match:
            return match.group(1)
    return ""


def _report_year(anchor, href: str, name: str) -> str:
    """Resolve the report year without promoting an ambiguous date.

    Webflow's live OCS index currently links insurer cards to internal
    ``/informes-anuales/...`` CMS item pages rather than directly to the PDF.
    Those slugs frequently carry the year. Prefer the surrounding year heading;
    use a unique year token in the official href/display text only as a fallback.
    """
    nearest = _nearest_year(anchor)
    if nearest:
        return nearest
    tokens = _YEAR_ANY_RE.findall(f"{href} {name}")
    unique = sorted(set(tokens))
    return unique[0] if len(unique) == 1 else ""


def parse_annual_reports(
    page_html: str,
    *,
    source_url: str,
    retrieved_at: str,
) -> list[dict]:
    doc = lxml_html.fromstring(page_html)
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for anchor in doc.xpath("//a[@href]"):
        href = str(anchor.get("href") or "").strip()
        name = _clean(anchor.text_content())
        if not href or not name:
            continue
        lower = href.casefold()
        is_direct_document = any(
            token in lower for token in (".pdf", "document", "download", "media", "files")
        )
        is_official_report_item = "/informes-anuales/" in lower
        if not (is_direct_document or is_official_report_item):
            continue
        year = _report_year(anchor, href, name)
        if not year:
            continue
        report_url = urljoin(source_url, href)
        key = (year, name, report_url)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "source_record_id": _sid(year, name, report_url),
                "report_year_raw": year,
                "insurer_name_raw": name,
                "report_url": report_url,
                "source_url": source_url,
                "retrieved_at_utc": retrieved_at,
            }
        )

    if not rows:
        raise RuntimeError("OCS annual-report parser found zero report links")
    return rows


def _get(session: requests.Session, url: str) -> tuple[requests.Response, str]:
    response = session.get(url, timeout=HTTP.timeout)
    response.raise_for_status()
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return response, retrieved_at


def _assert_unique(df: pd.DataFrame, column: str, label: str) -> None:
    if df[column].isna().any() or df[column].eq("").any():
        raise RuntimeError(f"{label}: null/empty {column}")
    if df[column].duplicated().any():
        raise RuntimeError(f"{label}: duplicate {column}")


def _snapshot_entry(
    response: requests.Response,
    *,
    retrieved_at: str,
    raw_file: str,
    observation_grain: str,
    retained_rows: int,
) -> dict:
    raw = response.content
    return {
        "observation_grain": observation_grain,
        "url": response.url,
        "retrieved_at_utc": retrieved_at,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw_file": raw_file,
        "retained_rows": retained_rows,
    }


def run(root: Path | None = None, *, force: bool = False) -> dict:
    root = root or PROJECT_ROOT
    insurers_path = root / INSURERS_OUT_REL
    annual_path = root / ANNUAL_OUT_REL
    if not force and file_has_data(insurers_path) and file_has_data(annual_path):
        insurers_existing = pd.read_csv(insurers_path, dtype=str, low_memory=False)
        annual_existing = pd.read_csv(annual_path, dtype=str, low_memory=False)
        return {
            "rows": len(insurers_existing) + len(annual_existing),
            "paths": [str(insurers_path), str(annual_path)],
            "snapshot_manifest": "",
            "errors": [],
        }

    run_started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    snapshot_base = os.getenv("GUIDE_SOURCE_SNAPSHOT_DIR", "").strip()
    snapshot_run: Path | None = None
    if snapshot_base:
        run_token = run_started_at.replace(":", "").replace("+00:00", "Z")
        snapshot_run = Path(snapshot_base) / SOURCE_ID / run_token
        snapshot_run.mkdir(parents=True, exist_ok=False)

    logger = setup_logging("scrape_ocs_insurers")
    session = build_session(HTTP.user_agent, HTTP.extra_headers)
    try:
        insurer_response, insurer_at = _get(session, INSURERS_URL)
        annual_response, annual_at = _get(session, ANNUAL_URL)
    finally:
        session.close()

    insurers = pd.DataFrame(
        parse_insurers(
            insurer_response.text,
            source_url=INSURERS_URL,
            retrieved_at=insurer_at,
        ),
        columns=INSURER_COLUMNS,
    )
    annual = pd.DataFrame(
        parse_annual_reports(
            annual_response.text,
            source_url=ANNUAL_URL,
            retrieved_at=annual_at,
        ),
        columns=ANNUAL_COLUMNS,
    )
    _assert_unique(insurers, "source_record_id", "OCS insurers")
    _assert_unique(annual, "source_record_id", "OCS annual reports")

    insurers = apply_post_ingest(insurers, source_id=SOURCE_ID, root=root)
    annual = apply_post_ingest(annual, source_id=SOURCE_ID, root=root)
    insurers_path.parent.mkdir(parents=True, exist_ok=True)
    insurers.to_csv(insurers_path, index=False, encoding="utf-8")
    annual.to_csv(annual_path, index=False, encoding="utf-8")

    manifest_path = ""
    if snapshot_run is not None:
        raw_insurers_name = "current_insurers.html"
        raw_annual_name = "annual_reports.html"
        (snapshot_run / raw_insurers_name).write_bytes(insurer_response.content)
        (snapshot_run / raw_annual_name).write_bytes(annual_response.content)
        insurers_bytes = insurers_path.read_bytes()
        annual_bytes = annual_path.read_bytes()
        manifestations = [
            _snapshot_entry(
                insurer_response,
                retrieved_at=insurer_at,
                raw_file=raw_insurers_name,
                observation_grain="current_insurer_listing",
                retained_rows=len(insurers),
            ),
            _snapshot_entry(
                annual_response,
                retrieved_at=annual_at,
                raw_file=raw_annual_name,
                observation_grain="historical_annual_report_index",
                retained_rows=len(annual),
            ),
        ]
        manifest = {
            "schema_version": "guide_source_snapshot_manifest_v1",
            "source_id": SOURCE_ID,
            "run_started_at_utc": run_started_at,
            "manifestations": manifestations,
            "schemas": {
                "current_insurer_listing": {
                    "columns": list(insurers.columns),
                    "schema_fingerprint": _schema_fingerprint(list(insurers.columns)),
                },
                "historical_annual_report_index": {
                    "columns": list(annual.columns),
                    "schema_fingerprint": _schema_fingerprint(list(annual.columns)),
                },
            },
            "processed_outputs": [
                {
                    "path": INSURERS_OUT_REL,
                    "row_count": len(insurers),
                    "byte_size": len(insurers_bytes),
                    "sha256": hashlib.sha256(insurers_bytes).hexdigest(),
                },
                {
                    "path": ANNUAL_OUT_REL,
                    "row_count": len(annual),
                    "byte_size": len(annual_bytes),
                    "sha256": hashlib.sha256(annual_bytes).hexdigest(),
                },
            ],
            "temporal_invariant": (
                "The current insurer listing and historical annual-report index are distinct "
                "observation grains. A historical report does not prove current license/status."
            ),
            "identity_invariant": (
                "OCS display cards are retained as displayed and are not silently split or merged "
                "into legal entities without a separate authoritative identifier binding."
            ),
            "certification_scope_note": (
                "This source freeze supports bounded guide insurance routes only and does not imply "
                "complete Puerto Rico finance coverage."
            ),
        }
        manifest_file = snapshot_run / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        manifest_path = str(manifest_file)

    logger.info(
        "OCS: %s current insurer rows; %s annual-report observations",
        len(insurers),
        len(annual),
    )
    return {
        "rows": len(insurers) + len(annual),
        "paths": [str(insurers_path), str(annual_path)],
        "snapshot_manifest": manifest_path,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"OCS insurer registry: {result['rows']:,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
