"""Ingest PRASA Capital Expenditure Report (CER), CIP, and completed-project exports.

Registry ``producer_script`` for three P0 PRASA financial-infrastructure sources:

  - ``prasa_cer``                CER / audited financial-statement line items
  - ``prasa_cip``                Capital Improvement Program project list
  - ``prasa_completed_projects`` Completed projects (FEMA 406 / COR3 recovery bridge)

PRASA publishes these as PDFs; operators extract them to CSV and drop them under the
per-source dropzone (``data/raw/PRASA/<cer|cip|completed>/``). This reader normalizes
those CSVs onto a tolerant canonical schema. No network; with no dropzone files it is a
clean no-op (writes nothing, reports ``EMPTY``) so the readiness preflight imports it
without side effects.

Usage:
  python3 scripts/ingest_prasa_cer.py                  # all three
  python3 scripts/ingest_prasa_cer.py --source prasa_cer
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging

# Shared canonical schema (flexible across financial line items and project rows).
CANONICAL_COLUMNS = ["fiscal_year", "item", "amount_usd", "category", "source_system"]

FISCAL_YEAR_ALIASES = (
    "fiscal_year",
    "fy",
    "ano_fiscal",
    "año_fiscal",
    "year",
    "ano",
    "año",
    "periodo",
)
ITEM_ALIASES = (
    "item",
    "account",
    "cuenta",
    "project",
    "proyecto",
    "descripcion",
    "descripción",
    "concepto",
    "obra",
)
AMOUNT_ALIASES = (
    "amount_usd",
    "amount",
    "monto",
    "cost",
    "costo",
    "value",
    "valor",
    "total",
    "cuantia",
    "cuantía",
)
CATEGORY_ALIASES = (
    "category",
    "categoria",
    "categoría",
    "status",
    "estatus",
    "type",
    "tipo",
    "fase",
    "completion_date",
    "fecha",
)

SOURCES = {
    "prasa_cer": {
        "subdir": "cer",
        "output": "data/staging/processed/pr_prasa_cer.csv",
    },
    "prasa_cip": {
        "subdir": "cip",
        "output": "data/staging/processed/pr_prasa_cip.csv",
    },
    "prasa_completed_projects": {
        "subdir": "completed",
        "output": "data/staging/processed/pr_prasa_completed_projects.csv",
    },
}


def _pick(record: dict, aliases: tuple[str, ...]) -> str:
    lower = {str(k).strip().lower(): v for k, v in record.items()}
    for alias in aliases:
        if alias in lower and lower[alias] not in (None, ""):
            return str(lower[alias]).strip()
    return ""


def _clean_amount(value: str) -> str:
    s = value.replace("$", "").replace(",", "").strip()
    if s in ("", "-", "—"):
        return ""
    try:
        return str(float(s))
    except ValueError:
        return ""


def _read_dropzone(root: Path, subdir: str) -> list[dict]:
    drop = root / "data" / "raw" / "PRASA" / subdir
    if not drop.exists():
        return []
    rows: list[dict] = []
    for csv_path in sorted(drop.glob("*.csv")):
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def normalize(records: list[dict], source_id: str) -> list[dict]:
    """Map operator-extracted rows onto the canonical schema. Pure — no I/O."""
    out: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        row = {
            "fiscal_year": _pick(rec, FISCAL_YEAR_ALIASES),
            "item": _pick(rec, ITEM_ALIASES),
            "amount_usd": _clean_amount(_pick(rec, AMOUNT_ALIASES)),
            "category": _pick(rec, CATEGORY_ALIASES),
            "source_system": source_id,
        }
        if not row["item"] and not row["amount_usd"]:
            continue
        out.append(row)
    out.sort(key=lambda r: (r["fiscal_year"], r["item"], r["amount_usd"]))
    return out


def _write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def materialize_source(root: Path, source_id: str, logger) -> dict:
    cfg = SOURCES[source_id]
    out_path = root / cfg["output"]
    rows = normalize(_read_dropzone(root, cfg["subdir"]), source_id)
    _write_csv(rows, out_path)
    status = "OK" if rows else "EMPTY"
    if rows:
        logger.info(f"  [{source_id}] {len(rows)} rows → {cfg['output']}")
    else:
        logger.info(f"  [{source_id}] no dropzone CSVs in data/raw/PRASA/{cfg['subdir']}/ — EMPTY")
    return {"source": source_id, "rows": len(rows), "status": status, "path": str(out_path)}


def run(root: Path | None = None, source: str | None = None) -> dict:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("ingest_prasa_cer")
    keys = [source] if source else list(SOURCES)
    results = [materialize_source(root, k, logger) for k in keys]
    total = sum(r["rows"] for r in results)
    return {"rows": total, "status": "OK" if total else "EMPTY", "sources": results}


# Entrypoint aliases recognized by the pipeline readiness preflight.
main = run


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=list(SOURCES), default=None)
    args = parser.parse_args(argv)
    result = run(source=args.source)
    print(f"prasa_cer: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
