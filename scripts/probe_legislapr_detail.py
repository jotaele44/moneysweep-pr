"""Probe LegislaPR measure detail pages for discovery-only legislative signals.

LegislaPR is treated as a T2 discovery/enrichment surface. Records produced by
this script remain blocked from canonical promotion unless the detail page exposes
cross-confirmation links to OpenStates and the official Assembly/SUTRA text.

Usage:
  python scripts/probe_legislapr_detail.py --url "https://www.legislapr.com/bills/PS%20782"
  python scripts/probe_legislapr_detail.py --input data/manual/legislapr/measure_urls.txt
"""

from __future__ import annotations

import logging

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts.config import PROJECT_ROOT, setup_logging
except Exception:  # pragma: no cover - keeps parser testable in isolation
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def setup_logging(log_name: str, log_dir: Path | None = None) -> logging.Logger:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        return logging.getLogger(log_name)


LEGISLAPR_BASE = "https://www.legislapr.com"
DEFAULT_OUTPUT = "data/staging/processed/pr_legislapr_measures_probe.json"
USER_AGENT = "MoneySweep-PR/1.0 (+legislative discovery; contact via repo)"

FISCAL_TERMS = {
    "appropriation",
    "appropriations",
    "asignacion",
    "asignación",
    "asignaciones",
    "presupuesto",
    "budget",
    "fondos",
    "funds",
    "fondo",
    "contrato",
    "contratos",
    "contract",
    "contracts",
    "emergencia",
    "emergency",
    "bonos",
    "bonds",
    "deuda",
    "debt",
    "subvencion",
    "subvención",
    "grant",
    "grants",
    "incentivo",
    "incentivos",
    "luma",
    "prepa",
    "aee",
    "cor3",
    "reconstruccion",
    "reconstrucción",
}

MEASURE_ID_RE = re.compile(r"\b(?:P\s*(?:del\s*)?[CS]|R\s*(?:C|CC|CS|S)|NM)\s*\d{1,5}\b", re.I)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


@dataclass(frozen=True)
class LegislativeMeasureProbe:
    measure_id: str
    measure_type: str
    chamber: str
    session: str
    status: str
    title: str
    summary: str
    authors: list[str]
    document_urls: list[str]
    openstates_url: str
    sutra_url: str
    fiscal_language_detected: bool
    promotion_status: str
    source_system: str
    source_url: str
    extraction_confidence: float
    ingestion_timestamp: str


class _LegislaPRHTMLParser(HTMLParser):
    """Small stdlib parser for resilient detail-page discovery.

    The site is treated as a rendered HTML surface; this parser avoids adding a
    BeautifulSoup/lxml dependency and extracts enough text and links to quantify
    coverage without making promotion decisions from unconfirmed text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self.text_chunks: list[str] = []
        self.title = ""
        self.meta_description = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): v or "" for k, v in attrs}
        if tag.lower() == "a" and attr.get("href"):
            self._current_href = attr["href"]
            self._current_text = []
        elif tag.lower() == "title":
            self._in_title = True
        elif tag.lower() == "meta":
            name = attr.get("name", "").lower()
            prop = attr.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.meta_description = _clean_text(attr.get("content", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href:
            self.links.append((self._current_href, _clean_text(" ".join(self._current_text))))
            self._current_href = None
            self._current_text = []
        elif tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        cleaned = _clean_text(data)
        if not cleaned:
            return
        self.text_chunks.append(cleaned)
        if self._current_href:
            self._current_text.append(cleaned)
        if self._in_title:
            self.title = _clean_text(f"{self.title} {cleaned}")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _canonical_measure_id(value: str) -> str:
    value = unquote(value or "")
    value = value.replace("_", " ").replace("-", " ")
    value = re.sub(r"\s+", " ", value).strip().upper()
    value = value.replace("P DEL C", "PC").replace("P DEL S", "PS")
    value = value.replace("P C", "PC").replace("P S", "PS")
    value = value.replace("R C S", "RCS").replace("R C C", "RCC")
    value = value.replace("R S", "RS").replace("R C", "RC")
    return re.sub(r"\s+", "", value)


def measure_id_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    candidate = unquote(path.split("/")[-1]) if path else ""
    match = MEASURE_ID_RE.search(candidate) or MEASURE_ID_RE.search(unquote(url))
    return _canonical_measure_id(match.group(0) if match else candidate)


def _absolute_url(base_url: str, href: str) -> str:
    return urljoin(base_url, href)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in seen:
            out.append(clean)
            seen.add(clean)
    return out


def _extract_field(text: str, labels: Iterable[str]) -> str:
    joined_labels = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"(?:{joined_labels})\s*:?\s*([^|\n\r]{{2,140}})", re.I)
    match = pattern.search(text)
    return _clean_text(match.group(1)) if match else ""


def _fiscal_language_detected(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in FISCAL_TERMS)


def _promotion_status(openstates_url: str, sutra_url: str) -> str:
    if openstates_url and sutra_url:
        return "cross_confirmed_candidate"
    return "blocked_pending_canonical_confirmation"


def _confidence(measure_id: str, title: str, openstates_url: str, sutra_url: str) -> float:
    score = 0.20
    if measure_id:
        score += 0.25
    if title:
        score += 0.15
    if openstates_url:
        score += 0.20
    if sutra_url:
        score += 0.20
    return round(min(score, 1.0), 2)


def parse_legislapr_detail(html: str, source_url: str) -> LegislativeMeasureProbe:
    parser = _LegislaPRHTMLParser()
    parser.feed(html)

    full_text = _clean_text(" | ".join(parser.text_chunks))
    title = parser.title or _extract_field(full_text, ["Título", "Titulo", "Title"])
    summary = parser.meta_description or _extract_field(
        full_text, ["Resumen", "Summary", "Descripción", "Descripcion"]
    )
    measure_id = measure_id_from_url(source_url)
    if not measure_id:
        match = MEASURE_ID_RE.search(full_text)
        measure_id = _canonical_measure_id(match.group(0)) if match else ""

    absolute_links = [(_absolute_url(source_url, href), label) for href, label in parser.links]
    embedded_urls = [(url, "") for url in URL_RE.findall(html)]
    all_urls = _dedupe(url for url, _label in [*absolute_links, *embedded_urls])

    openstates_url = next((u for u in all_urls if "openstates.org" in u.lower()), "")
    sutra_url = next(
        (
            u
            for u in all_urls
            if "sutra" in u.lower() or "oslpr.org" in u.lower() or "senado.pr.gov" in u.lower()
        ),
        "",
    )
    document_urls = _dedupe(
        u
        for u in all_urls
        if any(token in u.lower() for token in ["pdf", "document", "doc", "sutra", "oslpr"])
    )

    authors_text = _extract_field(
        full_text, ["Autores", "Authors", "Radicado por", "Presentado por"]
    )
    authors = [a.strip(" ,;") for a in re.split(r",|;| y ", authors_text) if a.strip(" ,;")]

    return LegislativeMeasureProbe(
        measure_id=measure_id,
        measure_type=_extract_field(full_text, ["Tipo", "Measure Type", "Type"]),
        chamber=_extract_field(full_text, ["Cámara", "Camara", "Chamber"]),
        session=_extract_field(full_text, ["Sesión", "Sesion", "Session"]),
        status=_extract_field(full_text, ["Estado", "Status"]),
        title=title,
        summary=summary,
        authors=authors,
        document_urls=document_urls,
        openstates_url=openstates_url,
        sutra_url=sutra_url,
        fiscal_language_detected=_fiscal_language_detected(full_text),
        promotion_status=_promotion_status(openstates_url, sutra_url),
        source_system="legislapr_discovery",
        source_url=source_url,
        extraction_confidence=_confidence(measure_id, title, openstates_url, sutra_url),
        ingestion_timestamp=datetime.now(timezone.utc).isoformat(),
    )


def fetch_html(url: str, timeout: int = 30) -> str:
    request = Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Language": "es-PR,es;q=0.9,en;q=0.8"}
    )
    with urlopen(request, timeout=timeout) as response:  # nosec: public legislative source URL from operator input
        return response.read().decode("utf-8", errors="replace")


def _read_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    if args.url:
        urls.extend(args.url)
    if args.input:
        path = Path(args.input)
        urls.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    return _dedupe(urls)


def run(
    urls: Iterable[str], root: Path | None = None, output: str = DEFAULT_OUTPUT
) -> dict[str, object]:
    root = Path(root or PROJECT_ROOT)
    out_path = root / output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("probe_legislapr_detail", log_dir=root / "data" / "logs")

    rows: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for url in urls:
        try:
            html = fetch_html(url)
            rows.append(asdict(parse_legislapr_detail(html, url)))
        except (OSError, URLError, TimeoutError, ValueError) as exc:
            logger.warning("LegislaPR probe failed for %s: %s", url, exc)
            errors.append({"url": url, "error": str(exc)})

    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    cross_confirmed = sum(
        1 for row in rows if row.get("promotion_status") == "cross_confirmed_candidate"
    )
    return {
        "status": "OK" if rows else "EMPTY",
        "rows": len(rows),
        "cross_confirmed_candidates": cross_confirmed,
        "errors": errors,
        "output": str(out_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe LegislaPR detail pages for T2 legislative discovery records"
    )
    parser.add_argument(
        "--url", action="append", help="LegislaPR measure detail URL. May be repeated."
    )
    parser.add_argument("--input", help="Text file of LegislaPR measure URLs, one per line.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Repo-relative JSON output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    urls = _read_urls(args)
    if not urls:
        parser.error("provide --url or --input")
    result = run(urls, output=args.output)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
