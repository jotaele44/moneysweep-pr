"""PR Treasury Sales & Use Tax (IVU/SUT) monthly collections — live PDF producer.

Fetches the live Hacienda "Distribución de Recaudos Mensuales" (Distribution of Monthly
Collections) PDFs from the IVU/SUT statistics subpage and materializes
``data/staging/processed/pr_hacienda_sut_ivu.csv``. This graduates ``hacienda_sut_ivu``
out of ``scripts/download_coverage_gap_intake.py`` (see that module's docstring): its
claim that this producer "needs network egress ... which the buildout environment does
not have" no longer holds — hacienda.pr.gov is reachable with no authentication.

SOURCE PAGE
-----------
https://hacienda.pr.gov/inversionistas/estadisticas-y-recaudos-statistics-and-revenues/
ingresos-del-impuesto-sobre-ventas-y-uso-ivu-sales-and-use-tax-sut-revenues

The page links one PDF per fiscal year (recent years going back to 2007), each a table of
IVU/SUT categories (5.5% SUT, 4.5% SUT Surcharge, 4% Services SUT, 0.5% FAM SUT,
1% Municipal SUT, Subtotal, Penalties/Interest/Others, Total SUT Collections, three
"Unallocated SUT Collections" balance lines, General Fund) by month, in thousands of
dollars, for one fiscal year (July-June).

SCOPE — CURRENT REPORTING TEMPLATE ONLY (documented limitation, not a bug)
---------------------------------------------------------------------------
Hacienda's report template changed at some point in its history: PDFs from around FY2018-19
and earlier use a different, incompatible layout — multiple fiscal years per table (columns
like "2016-17 / 2017-18 / 2018-19") and fund-based categories ("COFINA", "Fondo General",
"FAM", "Fondo Cine") rather than the current tax-tranche categories this parser targets.
Sampled and confirmed directly: ``distribucion_mensual_ivu_jun_2018-19_2.pdf`` uses the old
template; ``distribucion_de_recaudos_mensuales-_ivu-junio_2026.pdf`` uses the current one.

This producer identifies the current template at parse time by checking for the page header
"Año Fiscal / Fiscal Year <YYYY>-<YYYY>" (singular year) rather than "Años Fiscales / Fiscal
Years ... - ... - ..." (plural, old template), and silently skips any PDF that doesn't match
— it does not attempt to parse the old layout. Given ``update_cadence: monthly``, what matters
operationally is keeping the current-template PDFs (which cover the last several fiscal years
and are updated monthly) fresh; full historical backfill through the old template is a
separate, unscoped follow-on.

WHY WORD-LEVEL EXTRACTION, NOT ``extract_tables()``
----------------------------------------------------
These PDFs have a rendering quirk: numbers are sometimes split into two font runs mid-digit
(e.g. the six-digit value 150,830 renders as two words, "1" and "50,830", with a ~0pt gap
between them — verified directly by inspecting word bounding boxes). ``extract_tables()``
returns these as separate cells and a naive header-zip breaks. This parser instead merges
adjacent words on the same text line into one token whenever the horizontal gap between them
is under ``MERGE_GAP_PT`` (0.5pt) — the true within-number kerning gap measured at -0.04 to
0.03pt is two orders of magnitude below the smallest real word gap measured (1.28pt) and three
orders below real column gaps (11-31pt), so the threshold has a wide, safe margin.

Superscript footnote markers (e.g. "5.5% SUT ¹") are lone single digits that sit before an
unusually large gap (150-185pt measured, vs. 11-31pt for real inter-column gaps) to the next
real token; ``strip_footnote_markers`` drops them on that basis rather than by digit value,
since footnote numbers and real data digits are otherwise indistinguishable.

SELF-VALIDATION
----------------
A category row is only emitted if merging yields exactly 13 numeric tokens (12 months +
fiscal-year total) — anything else means the extraction missed or misattributed a token, and
the row is dropped rather than guessed. For the additive ("flow") categories, monthly values
are also checked against the annual total (rounding-tolerant); the three "Unallocated SUT
Collections" balance lines are point-in-time stock values (not sums of monthly flows — the
"Net Increase (Decrease)" annual figure is Ending Balance minus Starting Balance, confirmed
against the sample data, not a sum of the twelve monthly deltas) and are exempted from that
check by design, not by omission.

No-egress safe: any HTTP/parse failure is caught, logged, and degrades to an empty result
without raising — the readiness preflight imports this module without touching the network.

Usage:
  python3 scripts/download_hacienda_sut_ivu.py [--max-files N]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from scripts.config import PROJECT_ROOT, setup_logging

SOURCE_PAGE = (
    "https://hacienda.pr.gov/inversionistas/estadisticas-y-recaudos-statistics-and-revenues/"
    "ingresos-del-impuesto-sobre-ventas-y-uso-ivu-sales-and-use-tax-sut-revenues"
)
USER_AGENT = "ContractSweeper/1.0 (+https://github.com/jotaele44/moneysweep-pr)"
OUTPUT = "data/staging/processed/pr_hacienda_sut_ivu.csv"
DEFAULT_MAX_FILES = 12
MAX_RETRIES = 3
RETRY_BACKOFF = (5, 15, 30)

MERGE_GAP_PT = 0.5  # merges same-number word fragments; real word/column gaps are >= 1.28pt
ROW_CLUSTER_TOL_PT = 3.0  # groups words into a visual text line despite sub-pixel top drift
# Real inter-column gaps measured 11-36pt across sampled fiscal years; footnote-marker gaps
# (a lone digit before the first real data column) measured 67-185pt. 50pt sits with a safe
# margin on both sides — confirmed against FY2025-26 and FY2023-24 samples.
FOOTNOTE_GAP_PT = 50.0
FLOW_TOLERANCE_FRACTION = 0.02  # rounding-tolerant; each cell is independently rounded in the PDF

MONTH_ORDER = [
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
]

CATEGORY_MAP = [
    (re.compile(r"^5\.5%\s*SUT\b", re.I), "5.5% SUT"),
    (re.compile(r"^4\.5%\s*SUT\s*Surcharge", re.I), "4.5% SUT Surcharge"),
    (re.compile(r"^4%\s*Services\s*SUT", re.I), "4% Services SUT"),
    (re.compile(r"^0\.5%\s*FAM\s*SUT", re.I), "0.5% FAM SUT"),
    (re.compile(r"^1%\s*Municipal\s*SUT", re.I), "1% Municipal SUT"),
    (re.compile(r"^Subtotal\b", re.I), "Subtotal"),
    (re.compile(r"^Penalties", re.I), "Penalties, Interest and Others"),
    (re.compile(r"^Total\s*SUT\s*Collections", re.I), "Total SUT Collections"),
    (re.compile(r"^Starting\s*Balance", re.I), "Unallocated: Starting Balance"),
    (re.compile(r"^Net\s*Increase", re.I), "Unallocated: Net Increase (Decrease)"),
    (re.compile(r"^Ending\s*Balance", re.I), "Unallocated: Ending Balance"),
    (re.compile(r"^General\s*Fund", re.I), "General Fund"),
]
# Point-in-time balances, not sums of the twelve monthly figures — see docstring.
STOCK_CATEGORIES = {
    "Unallocated: Starting Balance",
    "Unallocated: Ending Balance",
    "Unallocated: Net Increase (Decrease)",
}

CURRENT_TEMPLATE_HEADER_RE = re.compile(
    r"A[ñn]o\s+Fiscal\s*/\s*Fiscal\s+Year\s+(\d{4})-(\d{4})", re.I
)
OLD_TEMPLATE_HEADER_RE = re.compile(r"A[ñn]os\s+Fiscales\s*/\s*Fiscal\s+Years", re.I)

NUM_TOKEN_RE = re.compile(r"^\(?-?\d[\d,]*(?:\.\d+)?\)?$")
LONE_DIGIT_RE = re.compile(r"^\d$")

CANONICAL_COLUMNS = [
    "fiscal_year",
    "period",
    "category",
    "amount_usd",
    "source_file",
    "source_system",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf"})
    return s


def _get(session: requests.Session, url: str, logger, *, binary: bool = False):
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            return resp.content if binary else resp.text
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.warning(f"  All {MAX_RETRIES} attempts failed for {url}: {exc}")
    return None


def discover_pdf_urls(session: requests.Session, logger) -> list[str]:
    html = _get(session, SOURCE_PAGE, logger)
    if not html:
        return []
    hrefs = re.findall(r'href="([^"]+\.pdf)"', html, re.I)
    urls = []
    seen = set()
    for href in hrefs:
        text_l = href.lower()
        if "distribucion" not in text_l and "distrbucion" not in text_l:
            continue
        if "ivu" not in text_l and "recaudos" not in text_l and "collections" not in text_l:
            continue
        url = urljoin(SOURCE_PAGE, href)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _merge_row_tokens(words: list[dict]) -> list[dict]:
    words = sorted(words, key=lambda w: w["x0"])
    tokens: list[dict] = []
    for w in words:
        if tokens and (w["x0"] - tokens[-1]["x1"]) < MERGE_GAP_PT:
            tokens[-1]["text"] += w["text"]
            tokens[-1]["x1"] = w["x1"]
        else:
            tokens.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"]})
    return tokens


def _cluster_rows(words: list[dict]) -> list[list[dict]]:
    words = sorted(words, key=lambda w: w["top"])
    clusters: list[list[dict]] = []
    for w in words:
        if clusters and abs(w["top"] - clusters[-1][-1]["top"]) <= ROW_CLUSTER_TOL_PT:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    return clusters


def _strip_footnote_markers(numeric_tokens: list[dict]) -> list[dict]:
    out = []
    for i, t in enumerate(numeric_tokens):
        gap_to_next = numeric_tokens[i + 1]["x0"] - t["x1"] if i + 1 < len(numeric_tokens) else 0
        if LONE_DIGIT_RE.match(t["text"]) and gap_to_next > FOOTNOTE_GAP_PT:
            continue
        out.append(t)
    return out


def _parse_number(text: str) -> float | None:
    s = text.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    v = float(s)
    return -v if neg else v


def parse_pdf(pdf_bytes: bytes, source_file: str, logger) -> list[dict]:
    """Extract (fiscal_year, period, category, amount_usd) rows from one distribution PDF.

    Returns [] and logs a reason if the PDF isn't the current single-fiscal-year template,
    or if no category rows can be reconstructed cleanly.
    """
    import io

    try:
        import pdfplumber  # type: ignore
    except Exception:
        logger.warning("  pdfplumber not installed — skipping PDF extraction.")
        return []

    rows: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                full_text = page.extract_text() or ""
                if OLD_TEMPLATE_HEADER_RE.search(full_text):
                    logger.info(
                        f"  {source_file}: old multi-year template — skipping (out of scope)"
                    )
                    continue
                header = CURRENT_TEMPLATE_HEADER_RE.search(full_text)
                if not header:
                    continue
                fiscal_year = f"{header.group(1)}-{header.group(2)}"

                words = page.extract_words(x_tolerance=1)
                for row_words in _cluster_rows(words):
                    tokens = _merge_row_tokens(row_words)
                    line_text = " ".join(t["text"] for t in tokens).strip()
                    category = next(
                        (name for pat, name in CATEGORY_MAP if pat.match(line_text)), None
                    )
                    if category is None:
                        continue

                    numeric_tokens = [t for t in tokens if NUM_TOKEN_RE.match(t["text"])]
                    numeric_tokens = _strip_footnote_markers(numeric_tokens)
                    raw_values = [_parse_number(t["text"]) for t in numeric_tokens]
                    values: list[float] = [v for v in raw_values if v is not None]

                    # Additive (flow) categories always carry 12 months + an FY total (13).
                    # The three point-in-time balance rows (STOCK_CATEGORIES) sometimes omit
                    # the FY-total column entirely in older vintages — a balance has no
                    # meaningful "annual total" the way a flow does, so some report years
                    # print only the 12 monthly snapshots. Confirmed directly: the FY2023-24
                    # PDF has 12 columns for "Starting/Ending Balance"; FY2025-26 has 13.
                    allowed_counts: tuple[int, ...] = (
                        (12, 13) if category in STOCK_CATEGORIES else (13,)
                    )
                    if len(values) not in allowed_counts:
                        logger.warning(
                            f"  {source_file}: {category!r} yielded {len(values)} numeric "
                            f"tokens (want {allowed_counts}) — skipping row"
                        )
                        continue

                    has_annual = len(values) == 13
                    monthly = values[:12]
                    if has_annual:
                        annual = values[-1]
                        if category not in STOCK_CATEGORIES:
                            tolerance = max(2.0, abs(annual) * FLOW_TOLERANCE_FRACTION)
                            if abs(sum(monthly) - annual) > tolerance:
                                logger.warning(
                                    f"  {source_file}: {category!r} monthly sum "
                                    f"{sum(monthly):,.1f} vs annual {annual:,.1f} — skipping row"
                                )
                                continue

                    # PDF header states "(Miles de Dólares / In Thousands)".
                    for month, value in zip(MONTH_ORDER, monthly):
                        rows.append(
                            {
                                "fiscal_year": fiscal_year,
                                "period": month,
                                "category": category,
                                "amount_usd": value * 1000.0,
                                "source_file": source_file,
                                "source_system": "hacienda_sut_ivu",
                            }
                        )
                    if has_annual:
                        rows.append(
                            {
                                "fiscal_year": fiscal_year,
                                "period": "FY_Total",
                                "category": category,
                                "amount_usd": annual * 1000.0,
                                "source_file": source_file,
                                "source_system": "hacienda_sut_ivu",
                            }
                        )
    except Exception as exc:
        logger.warning(f"  Failed to parse {source_file}: {exc}")
    return rows


def _write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def run(root: Path | None = None, max_files: int = DEFAULT_MAX_FILES) -> dict:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("download_hacienda_sut_ivu")
    out_path = root / OUTPUT

    session = _session()
    try:
        urls = discover_pdf_urls(session, logger)[:max_files]
        all_rows: list[dict] = []
        parsed_files = 0
        for url in urls:
            content = _get(session, url, logger, binary=True)
            if not content:
                continue
            source_file = url.rsplit("/", 1)[-1]
            file_rows = parse_pdf(content, source_file, logger)
            if file_rows:
                parsed_files += 1
            all_rows.extend(file_rows)
    finally:
        session.close()

    all_rows.sort(key=lambda r: (r["fiscal_year"], r["category"], r["period"]))
    _write_csv(all_rows, out_path)
    status = "OK" if all_rows else "EMPTY"
    logger.info(
        f"  hacienda_sut_ivu: {len(all_rows)} rows from {parsed_files}/{len(urls)} "
        f"current-template PDFs — {status}"
    )
    return {"rows": len(all_rows), "status": status, "path": str(out_path)}


main = run
download = run
fetch = run


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    args = parser.parse_args(argv)
    result = run(max_files=args.max_files)
    print(f"hacienda_sut_ivu: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
