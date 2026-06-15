"""Shared lifecycle for the ``scripts/ingest_*.py`` dropzone-reader family.

Several PR-government and federal sources are credentialed portals or HTML/PDF
surfaces with no machine API: the only ingestion path is an operator dropping a
CSV/Excel export into ``data/raw/<DIR>/``. ``scripts/ingest_oce.py`` /
``ingest_donaciones.py`` each re-implemented the same reader: cache check,
empty-dropzone handling, case-insensitive Spanish/English column mapping, blank-key
filtering, concat + dedupe, CSV write.

This factors that out **once** so a new dropzone reader is just its
``RAW_DIR_NAME``, ``OUTPUT_COLUMNS``, ``COL_MAP`` and key field. Status vocabulary
and return shape match the hand-written readers exactly:
``{"rows", "path", "status"}`` with ``status`` in
``CACHED | NO_FILES | EMPTY | OK``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.config import setup_logging

__all__ = ["map_column", "parse_frame", "ingest_dropzone"]

_READABLE_SUFFIXES = (".csv", ".xlsx", ".xls")


def map_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first column in ``df`` matching a candidate (case/space-insensitive)."""
    df_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        actual = df_lower.get(cand.lower().strip())
        if actual is not None:
            return actual
    return None


def parse_frame(
    df: pd.DataFrame,
    *,
    source_file: str,
    output_columns: list[str],
    col_map: dict[str, list[str]],
    key_field: str,
) -> pd.DataFrame:
    """Map a raw frame onto ``output_columns`` and drop rows with a blank key field."""
    out: dict[str, object] = {}
    for target, candidates in col_map.items():
        src_col = map_column(df, candidates)
        out[target] = df[src_col].astype(str).str.strip() if src_col is not None else ""

    out_df = pd.DataFrame(out)
    out_df["source_file"] = source_file
    for col in output_columns:
        if col not in out_df.columns:
            out_df[col] = ""
    key = out_df[key_field].fillna("").astype(str).str.strip()
    out_df = out_df[(key != "") & (key.str.lower() != "nan")]
    return out_df[output_columns]


def ingest_dropzone(
    *,
    root: Path,
    raw_dir_name: str,
    output_path: str,
    output_columns: list[str],
    col_map: dict[str, list[str]],
    key_field: str,
    source_name: str,
    force: bool = False,
) -> dict:
    """Read every CSV/Excel in ``root/raw_dir_name`` into one normalized CSV.

    Mirrors ``ingest_oce.run``: cached non-empty output short-circuits unless
    ``force``; a missing/empty dropzone writes a header-only CSV; otherwise each
    file is column-mapped, blank-key rows are dropped, and the frames are
    concatenated and de-duplicated.
    """
    root = Path(root)
    raw_dir = root / raw_dir_name
    out_path = root / output_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(source_name)

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    if not raw_dir.exists():
        logger.info(f"  No raw dir at {raw_dir} — skipping ingest")
        pd.DataFrame(columns=output_columns).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    files = sorted(
        f
        for f in raw_dir.iterdir()
        if f.suffix.lower() in _READABLE_SUFFIXES and not f.name.startswith("~")
    )
    if not files:
        logger.info(f"  No files in {raw_dir} — skipping ingest")
        pd.DataFrame(columns=output_columns).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    logger.info(f"  Found {len(files)} export file(s) in {raw_dir}")
    frames = []
    for f in files:
        logger.info(f"  Reading {f.name}...")
        try:
            if f.suffix.lower() == ".csv":
                df = pd.read_csv(f, dtype=str, low_memory=False, encoding="utf-8")
            else:
                df = pd.read_excel(f, dtype=str)
            parsed = parse_frame(
                df,
                source_file=f.name,
                output_columns=output_columns,
                col_map=col_map,
                key_field=key_field,
            )
            logger.info(f"    → {len(parsed):,} rows after mapping")
            frames.append(parsed)
        except Exception as e:
            logger.warning(f"  Could not parse {f.name}: {e}")

    if not frames:
        logger.warning("  No parseable export files found")
        pd.DataFrame(columns=output_columns).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    combined = pd.concat(frames, ignore_index=True).drop_duplicates()
    combined.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(combined):,} rows)")
    return {"rows": len(combined), "path": str(out_path), "status": "OK"}
