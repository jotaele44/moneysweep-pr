#!/usr/bin/env python3
"""Probe LegislaPR measure detail pages for MoneySweep discovery.

This script intentionally treats LegislaPR as a T2 discovery surface. It does
not promote records to canonical status unless both an OpenStates reference and
an official Puerto Rico Legislative Assembly/SUTRA-style document reference are
present.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://www.legislapr.com"
SOURCE_ID = "legislapr_discovery"
DEFAULT_USER_AGENT = "moneysweep-pr/legislapr-discovery (+https://github.com/jotaele44/moneysweep-pr)"

MEASURE_RE = re.compile(r"\b(PC|PS|RCC|RCS|RC|RS|NM)\s*-?\s*(\d{1,5})\b", re.IGNORECASE)
FISCAL_KEYWORDS = {
    "asignacion",
    "asignación",
    "asignar",
    "fondos",
    "fondo",
    "presupuesto",
    "reembolso",
    "reembolsar",
    "subvencion",
    "subvención",
    "incentivo",
    "credito contributivo",
    "crédito contributivo",
    "municipio",
    "municipal",
    "ogp",
    "crim",
    "hacienda",
    "aafaf",
    "cor3",
    "fema",
    "cdbg",
    "contrato",
    "contratacion",
    "contratación",
}


@dataclass(frozen=True)
class LegislativeDiscoveryRecord:
    source_id: str
    measure_id: str
    detail_url: str
    openstates_url: str | None
    official_document_url: str | None
    outbound_urls: list[str]
    fiscal_signal: bool
    fiscal_terms: list[str]
    promotion_state: str


def normalize_measure_id(value: str) -> str:
    """Normalize LegislaPR/OpenStates-style Puerto Rico measure IDs.

    Examples:
        PS%20782 -> PS 782
        pc-1207 -> PC 1207
    """
    raw = unquote(str(value or "")).replace("_", " ").replace("-", " ")
    raw = re.sub(r"\s+", " ", raw.strip().upper())
    match = MEASURE_RE.search(raw)
    if not match:
        raise ValueError(f"Unsupported Puerto Rico measure id: {value!r}")
    return f"{match.group(1).upper()} {int(match.group(2))}"


def legislapr_detail_url(measure_id: str) -> str:
    normalized = normalize_measure_id(measure_id)
    return f"{BASE_URL}/bills/{quote(normalized)}"


def fetch_html(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - public source probe
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


def html_to_text(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_urls(html: str) -> list[str]:
    hrefs = re.findall(r"href=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)
    urls: list[str] = []
    for href in hrefs:
        url = urljoin(BASE_URL, unescape(href))
        if url not in urls:
            urls.append(url)
    return urls


def select_openstates_url(urls: Iterable[str]) -> str | None:
    for url in urls:
        if "openstates.org" in url.lower():
            return url
    return None


def select_official_document_url(urls: Iterable[str]) -> str | None:
    official_markers = (
        "sutra.oslpr.org",
        "sutra",
        "oslpr.org",
        "senado.pr.gov",
        "camara.pr.gov",
        "rcm.gov.pr",
    )
    for url in urls:
        lowered = url.lower()
        if any(marker in lowered for marker in official_markers):
            return url
    return None


def fiscal_terms(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(term for term in FISCAL_KEYWORDS if term in lowered)


def promotion_state(openstates_url: str | None, official_document_url: str | None) -> str:
    if openstates_url and official_document_url:
        return "cross_confirmed_ready"
    if openstates_url or official_document_url:
        return "partially_confirmed_hold"
    return "discovery_only_hold"


def probe_measure(measure_id: str, html: str | None = None) -> LegislativeDiscoveryRecord:
    normalized = normalize_measure_id(measure_id)
    url = legislapr_detail_url(normalized)
    page = html if html is not None else fetch_html(url)
    urls = extract_urls(page)
    text = html_to_text(page)
    openstates_url = select_openstates_url(urls)
    official_document_url = select_official_document_url(urls)
    terms = fiscal_terms(text)
    return LegislativeDiscoveryRecord(
        source_id=SOURCE_ID,
        measure_id=normalized,
        detail_url=url,
        openstates_url=openstates_url,
        official_document_url=official_document_url,
        outbound_urls=urls,
        fiscal_signal=bool(terms),
        fiscal_terms=terms,
        promotion_state=promotion_state(openstates_url, official_document_url),
    )


def iter_measure_ids(args: argparse.Namespace) -> Iterable[str]:
    if args.measure:
        yield from args.measure
    if args.input:
        with Path(args.input).open(newline="", encoding="utf-8") as handle:
            sample = handle.read(2048)
            handle.seek(0)
            if "," in sample or "\t" in sample:
                reader = csv.DictReader(handle)
                for row in reader:
                    value = row.get("measure_id") or row.get("bill_id") or row.get("id")
                    if value:
                        yield value
            else:
                for line in handle:
                    line = line.strip()
                    if line:
                        yield line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measure", action="append", help="Measure id, e.g. 'PS 782'. May be repeated.")
    parser.add_argument("--input", help="Text/CSV file containing measure ids.")
    parser.add_argument("--output", default="data/staging/processed/legislapr_measures_discovery.jsonl")
    parser.add_argument("--crosswalk-output", default="data/staging/processed/legislapr_measure_crosswalk.csv")
    args = parser.parse_args(argv)

    records = [probe_measure(measure) for measure in iter_measure_ids(args)]
    if not records:
        parser.error("Provide --measure or --input")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")

    crosswalk = Path(args.crosswalk_output)
    crosswalk.parent.mkdir(parents=True, exist_ok=True)
    with crosswalk.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "measure_id",
                "legislapr_url",
                "openstates_url",
                "official_document_url",
                "promotion_state",
                "fiscal_signal",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "measure_id": record.measure_id,
                    "legislapr_url": record.detail_url,
                    "openstates_url": record.openstates_url or "",
                    "official_document_url": record.official_document_url or "",
                    "promotion_state": record.promotion_state,
                    "fiscal_signal": str(record.fiscal_signal).lower(),
                }
            )

    print(f"wrote {output}")
    print(f"wrote {crosswalk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
