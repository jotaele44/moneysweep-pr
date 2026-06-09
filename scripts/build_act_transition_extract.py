"""Build the combined ACT/ACUDEN transition-contract extraction CSV from PDFs.

Reads the two operator-supplied §9(a)(12) transition PDFs (ACT 2020 and ACUDEN
2024) and flattens their per-page tables into a single 18-column CSV at
``data/raw/act_transition/transition_contracts_extracted.csv`` — the default
input of ``scripts/audit_act_alias_coverage.py``.

Both PDFs are digital-table PDFs that pdfplumber reads cleanly (one table per
page, uniform 8 columns, no wrapped/continuation rows). The column *order*
differs by source, so the mapping is per-source.

Unlike ``scripts/extract_act_acuden_pdfs.py`` (which canonicalizes
``contractor_name`` via alias overrides and writes per-source 6-column staging
CSVs), this builder keeps the RAW contractor name so the coverage audit can
still observe real spelling variants.

Usage:

    python3 scripts/build_act_transition_extract.py \
        --act-pdf path/to/Contratos_Vigentes_ACT.pdf \
        --acuden-pdf path/to/Informe_..._Transicion.pdf

Defaults look in the operator drop dirs (``data/manual/{act_transition,
acuden_2024}/``) for a single ``*.pdf`` each when the flags are omitted.

Pause-lock note: writes only the source-data CSV under ``data/raw/`` — does NOT
touch ``data/staging/processed/``.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

from scripts.config import PROJECT_ROOT, setup_logging

OUTPUT_COLUMNS = [
    "source_dataset",
    "agency_name",
    "transition_year",
    "source_pdf",
    "source_page",
    "source_table",
    "sec",
    "contract_number",
    "contractor_name",
    "award_date_raw",
    "start_date_raw",
    "end_date_raw",
    "amount_raw",
    "amount_numeric",
    "service_type",
    "comments",
    "base_contract_number",
    "contract_suffix",
]

DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "raw" / "act_transition" / "transition_contracts_extracted.csv"
)

# Per-source descriptors. ``order`` lists which schema field each PDF column maps
# to, left-to-right; ``None`` means the column is absent for that source.
SOURCES = {
    "act": {
        "source_dataset": "ACT_2020",
        "agency_name": "Autoridad de Carreteras y Transportación (ACT)",
        "transition_year": "2020",
        "source_pdf": "Contratos_Vigentes_ACT.pdf",
        # PDF column order: Núm. Contrato | Contratista | Otorgación | Inicio |
        # Terminación | Cuantía | Tipo de Servicio | Comentarios
        "order": [
            "contract_number",
            "contractor_name",
            "award_date_raw",
            "start_date_raw",
            "end_date_raw",
            "amount_raw",
            "service_type",
            "comments",
        ],
        "suffix_sep": " ",
    },
    "acuden": {
        "source_dataset": "ACUDEN_2024",
        "agency_name": "ACUDEN",
        "transition_year": "2024",
        "source_pdf": "Informe_Contratos_Vigentes_al_Momento_de_Transicion.pdf",
        # PDF column order: Sec | Núm. Contrato | Contratista | Otorgación |
        # Inicio | Terminación | Cuantía | Tipo de Servicio
        "order": [
            "sec",
            "contract_number",
            "contractor_name",
            "award_date_raw",
            "start_date_raw",
            "end_date_raw",
            "amount_raw",
            "service_type",
        ],
        "suffix_sep": "-",
    },
}

_CONTRACT_BASE = re.compile(r"^(\d{4}-\d{4,6})(?:[ -](.+))?$")
_WS = re.compile(r"\s+")


def _clean(cell: str | None) -> str:
    """Collapse internal whitespace (incl. cell newlines) and trim."""
    return _WS.sub(" ", (cell or "").replace("\n", " ")).strip()


def _amount_numeric(amount_raw: str) -> str:
    """Return the numeric string for an amount cell, or '' for null markers."""
    s = amount_raw.replace("$", "").replace(",", "").strip()
    if s in ("", "-", "—"):
        return ""
    try:
        return str(float(s))
    except ValueError:
        return ""


def _split_contract(contract_number: str, suffix_sep: str) -> tuple[str, str]:
    """Split a contract number into (base, suffix).

    ACT suffixes are space-separated ("1992-000228 C"); ACUDEN suffixes are
    hyphen-separated ("2022-000963-A"). The base is always "YYYY-NNNNNN".
    """
    m = _CONTRACT_BASE.match(contract_number)
    if not m:
        return contract_number, ""
    return m.group(1), (m.group(2) or "").strip()


def _is_header(row: list[str | None]) -> bool:
    return any("contratista" in (c or "").lower() for c in row)


def _resolve_pdf(flag: Path | None, drop_subdir: str, logger) -> Path | None:
    if flag is not None:
        return flag
    drop = PROJECT_ROOT / "data" / "manual" / drop_subdir
    if not drop.exists():
        return None
    pdfs = sorted(p for p in drop.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        return None
    if len(pdfs) > 1:
        logger.warning("Multiple PDFs in %s; using %s", drop, pdfs[0].name)
    return pdfs[0]


def extract_pdf(pdf_path: Path, source_key: str, logger) -> list[dict[str, str]]:
    cfg: dict = SOURCES[source_key]
    order = cfg["order"]
    rows: list[dict[str, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for table_no, table in enumerate(tables, start=1):
                for raw in table:
                    if _is_header(raw):
                        continue
                    cells = [_clean(c) for c in raw]
                    if not any(cells):
                        continue
                    field = {order[i]: cells[i] for i in range(min(len(order), len(cells)))}
                    contract_number = field.get("contract_number", "")
                    base, suffix = _split_contract(contract_number, cfg["suffix_sep"])
                    amount_raw = field.get("amount_raw", "")
                    rows.append(
                        {
                            "source_dataset": cfg["source_dataset"],
                            "agency_name": cfg["agency_name"],
                            "transition_year": cfg["transition_year"],
                            "source_pdf": cfg["source_pdf"],
                            "source_page": str(page_no),
                            "source_table": str(table_no),
                            "sec": field.get("sec", ""),
                            "contract_number": contract_number,
                            "contractor_name": field.get("contractor_name", ""),
                            "award_date_raw": field.get("award_date_raw", ""),
                            "start_date_raw": field.get("start_date_raw", ""),
                            "end_date_raw": field.get("end_date_raw", ""),
                            "amount_raw": amount_raw,
                            "amount_numeric": _amount_numeric(amount_raw),
                            "service_type": field.get("service_type", ""),
                            "comments": field.get("comments", ""),
                            "base_contract_number": base,
                            "contract_suffix": suffix,
                        }
                    )
    logger.info("  [%s] %s: %d rows", source_key, pdf_path.name, len(rows))
    return rows


def _write_csv(rows: list[dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--act-pdf", type=Path, default=None)
    parser.add_argument("--acuden-pdf", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    logger = setup_logging("build_act_transition_extract")
    act_pdf = _resolve_pdf(args.act_pdf, "act_transition", logger)
    acuden_pdf = _resolve_pdf(args.acuden_pdf, "acuden_2024", logger)

    if act_pdf is None and acuden_pdf is None:
        logger.error("No PDFs found. Pass --act-pdf and/or --acuden-pdf.")
        return 2

    rows: list[dict[str, str]] = []
    if act_pdf is not None:
        rows.extend(extract_pdf(act_pdf, "act", logger))
    if acuden_pdf is not None:
        rows.extend(extract_pdf(acuden_pdf, "acuden", logger))

    _write_csv(rows, args.output)
    logger.info("Wrote %s — %d rows", args.output.relative_to(PROJECT_ROOT), len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
