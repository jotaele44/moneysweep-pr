"""
Extract ACT and ACUDEN transition-contract tables from manually-dropped PDFs.

The ACT and ACUDEN sources are declared in ``registries/manual_export_registry.yaml``
with column schemas, but the underlying drops are digital-table PDFs that the
existing CSV/XLSX ingestor (``scripts/ingest_active_contractors.py``) cannot
read. This harness sits in front of that ingestor: operator drops PDFs into
``data/manual/{act_transition,acuden_2024}/``, this script extracts the
tabular rows into deterministic CSVs under ``data/staging/raw/``, and a
downstream ingestor can promote them to ``data/staging/processed/`` once the
pause-lock policy permits.

The extractor:

  * Walks each known drop directory for ``*.pdf`` files.
  * Looks up each PDF by SHA256 against ``data/raw/documents/documents_manifest.csv``
    and applies a per-document layout profile (column order, header skip,
    column-name map) when one exists. Falls back to a heuristic
    "first-table-per-page" profile for unknown documents.
  * Applies alias overrides (``contract_sweeper.runtime.alias_overrides``) to
    the ``contractor_name`` column so canonical clusters reach the staged CSV
    before any downstream join.
  * Writes one CSV per source PDF under
    ``data/staging/raw/{act_transition,acuden_2024}/<pdf_stem>.csv``. Output
    is deterministic: identical inputs → byte-identical CSV.

Usage:

    python3 scripts/extract_act_acuden_pdfs.py                  # all sources
    python3 scripts/extract_act_acuden_pdfs.py --source act     # ACT only
    python3 scripts/extract_act_acuden_pdfs.py --source acuden  # ACUDEN only
    python3 scripts/extract_act_acuden_pdfs.py --dry-run        # plan only

Pause-lock note: this script writes only under ``data/staging/raw/`` — it does
NOT touch ``data/staging/processed/``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

from contract_sweeper.runtime.alias_overrides import apply as apply_override
from contract_sweeper.runtime.alias_overrides import load_overrides
from scripts.config import PROJECT_ROOT, setup_logging


# ---------------------------------------------------------------------------
# Source profiles
# ---------------------------------------------------------------------------

# Output column order per manual_export_registry.yaml.
ACT_COLUMNS = [
    "contractor_name",
    "contract_number",
    "start_date",
    "end_date",
    "amount",
    "service_type",
]

ACUDEN_COLUMNS = [
    "contract_number",
    "contractor_name",
    "start_date",
    "end_date",
    "amount",
    "service_type",
]

SOURCES: dict[str, dict] = {
    "act": {
        "input_dir": "data/manual/act_transition",
        "output_dir": "data/staging/raw/act_transition",
        "columns": ACT_COLUMNS,
        "label": "act_transition_contracts",
    },
    "acuden": {
        "input_dir": "data/manual/acuden_2024",
        "output_dir": "data/staging/raw/acuden_2024",
        "columns": ACUDEN_COLUMNS,
        "label": "acuden_2024_transition",
    },
}

# Per-document layout profiles keyed by SHA256. Each profile names the column
# order *as it appears in the PDF table*, so we can re-order rows into the
# registry's canonical column order. Add entries here as operators drop new
# PDFs and confirm the layout.
LAYOUT_PROFILES: dict[str, dict] = {
    # Example placeholder — real entries get added when PDFs are dropped.
    # "<sha256>": {"source": "act", "pdf_columns": ["Vendor", "PIID", ...]},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _profile_for(pdf_sha: str, source_key: str) -> dict | None:
    """Return the layout profile for a PDF, or None to use heuristic mode."""
    profile = LAYOUT_PROFILES.get(pdf_sha)
    if profile and profile.get("source") == source_key:
        return profile
    return None


def _extract_tables(pdf_path: Path) -> list[list[list[str]]]:
    """Return one list-of-rows per detected table across all pages."""
    tables: list[list[list[str]]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue
                cleaned = [[(cell or "").strip() for cell in row] for row in table]
                tables.append(cleaned)
    return tables


def _looks_like_header(row: list[str], target_columns: list[str]) -> bool:
    """Heuristic: a header row contains at least two known column tokens."""
    joined = " ".join(row).lower()
    hits = sum(1 for col in target_columns if col.replace("_", " ") in joined)
    return hits >= 2


def _rows_from_tables(
    tables: list[list[list[str]]],
    columns: list[str],
    profile: dict | None,
) -> list[dict[str, str]]:
    """Flatten extracted PDF tables into target-schema dicts.

    With a layout profile: re-order each row by ``profile["pdf_columns"]``,
    drop the first row if it matches the header. Without a profile: assume
    the table's first row is the header, align by best-effort name match,
    else by positional fallback.
    """
    out: list[dict[str, str]] = []
    for table in tables:
        if not table:
            continue
        if profile:
            pdf_cols = profile["pdf_columns"]
            data_rows = table
            if _looks_like_header(table[0], columns) or _looks_like_header(table[0], pdf_cols):
                data_rows = table[1:]
            for raw in data_rows:
                if all(not cell for cell in raw):
                    continue
                row = dict(zip(pdf_cols, raw, strict=False))
                out.append({col: row.get(col, "") for col in columns})
        else:
            header = table[0]
            header_lower = [c.lower() for c in header]
            col_index: dict[str, int] = {}
            for col in columns:
                token = col.replace("_", " ").lower()
                for idx, h in enumerate(header_lower):
                    if token in h:
                        col_index[col] = idx
                        break
            data_rows = table[1:] if _looks_like_header(header, columns) else table
            for raw in data_rows:
                if all(not cell for cell in raw):
                    continue
                row: dict[str, str] = {}
                for idx, col in enumerate(columns):
                    if col in col_index and col_index[col] < len(raw):
                        row[col] = raw[col_index[col]]
                    elif idx < len(raw):
                        row[col] = raw[idx]
                    else:
                        row[col] = ""
                out.append(row)
    return out


def _apply_aliases(rows: list[dict[str, str]], overrides: dict[str, str]) -> None:
    """Canonicalize contractor_name in place when an override fires.

    Preserves the original casing of names that have no override entry so
    the staged CSV still reads like the source PDF; only known variants
    collapse into their canonical form.
    """
    for row in rows:
        name = row.get("contractor_name", "")
        if not name:
            continue
        canonical, overridden = apply_override(name, overrides)
        if overridden:
            row["contractor_name"] = canonical


def _write_csv(rows: list[dict[str, str]], columns: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Per-source driver
# ---------------------------------------------------------------------------


def extract_source(
    source_key: str,
    root: Path,
    overrides: dict[str, str],
    dry_run: bool,
    input_override: Path | None,
    logger,
) -> dict:
    """Extract every PDF for one source into staged CSVs.

    Returns ``{"pdfs": N, "rows": M, "outputs": [paths], "skipped": [...]}``.
    """
    cfg = SOURCES[source_key]
    in_dir = input_override or (root / cfg["input_dir"])
    out_dir = root / cfg["output_dir"]
    columns = cfg["columns"]
    label = cfg["label"]

    if not in_dir.exists():
        logger.warning(f"  [{label}] drop dir not found: {in_dir} — skipping")
        return {"pdfs": 0, "rows": 0, "outputs": [], "skipped": [str(in_dir)]}

    pdfs = sorted(p for p in in_dir.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        logger.info(f"  [{label}] no PDFs in {in_dir}")
        return {"pdfs": 0, "rows": 0, "outputs": [], "skipped": []}

    total_rows = 0
    outputs: list[str] = []
    for pdf_path in pdfs:
        pdf_sha = _sha256(pdf_path)
        profile = _profile_for(pdf_sha, source_key)
        try:
            tables = _extract_tables(pdf_path)
        except Exception as exc:
            logger.error(f"  [{label}] {pdf_path.name}: extraction failed ({exc})")
            continue

        rows = _rows_from_tables(tables, columns, profile)
        _apply_aliases(rows, overrides)

        out_path = out_dir / f"{pdf_path.stem}.csv"
        logger.info(
            f"  [{label}] {pdf_path.name}: {len(tables)} tables → {len(rows)} rows"
            f"{' (profile)' if profile else ' (heuristic)'}"
        )
        if dry_run:
            logger.info(f"    --dry-run: would write {out_path}")
        else:
            _write_csv(rows, columns, out_path)
            outputs.append(str(out_path))
        total_rows += len(rows)

    return {
        "pdfs": len(pdfs),
        "rows": total_rows,
        "outputs": outputs,
        "skipped": [],
    }


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


def extract(
    source: str = "all",
    root: Path | None = None,
    dry_run: bool = False,
    input_dir: Path | None = None,
) -> dict[str, dict]:
    """Run the extractor for ``act``, ``acuden``, or ``all``."""
    root = Path(root) if root is not None else PROJECT_ROOT
    logger = setup_logging("extract_act_acuden_pdfs")
    overrides = load_overrides()

    keys = list(SOURCES.keys()) if source == "all" else [source]
    if input_dir is not None and source == "all":
        raise ValueError("--input-dir requires --source act or --source acuden")

    summary: dict[str, dict] = {}
    for key in keys:
        summary[key] = extract_source(key, root, overrides, dry_run, input_dir, logger)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract ACT/ACUDEN transition-contract tables from PDFs"
    )
    parser.add_argument(
        "--source",
        choices=["act", "acuden", "all"],
        default="all",
        help="Which source to extract (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan extraction without writing CSV outputs",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Override the drop directory (requires --source act|acuden)",
    )
    args = parser.parse_args()

    summary = extract(
        source=args.source,
        dry_run=args.dry_run,
        input_dir=args.input_dir,
    )
    for key, info in summary.items():
        print(
            f"{key}: {info['pdfs']} pdf(s), {info['rows']} row(s)"
            + (" [dry-run]" if args.dry_run else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
