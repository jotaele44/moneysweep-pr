"""Extract tables from HigherGov PDFs into CSV for normalization.

HigherGov PDFs contain raw JSON API responses ({"results":[...]}).
Parse strategy (tried in order):
  1. pymupdf (fitz) — extract text, parse as JSON
  2. pdfplumber — extract tables
  3. pdftotext subprocess — layout text, parse as JSON then tabular
Writes CSVs to data/staging/expansion/ with names expected by normalization.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "HigherGov"
OUT_DIR = PROJECT_ROOT / "data" / "staging" / "expansion"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FILENAME_MAP = {
    "HigherGov PR Data (Municipal Awards)": "highergov_municipal_awards.csv",
    "HigherGov PR Data (IDV Awards)":       "highergov_idv_awards.csv",
    "HigherGov PR Data (Prime Awards)":     "highergov_prime_awards.csv",
    "HigherGov PR Data (Sub Awards)":       "highergov_sub_awards.csv",
}


def _parse_json_text(text: str) -> pd.DataFrame | None:
    """Try to parse text as a JSON API response with a 'results' list."""
    text = text.replace("Pretty-print\n", "").replace("Pretty-print", "").strip()
    for candidate in (text, re.sub(r"\n", "", text)):
        try:
            data = json.loads(candidate)
            records = data.get("results", data) if isinstance(data, dict) else data
            if isinstance(records, list) and records:
                return pd.json_normalize(records)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def parse_with_pymupdf(path: Path) -> pd.DataFrame | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(str(path))
        text = "".join(page.get_text("text") for page in doc)
        doc.close()
        return _parse_json_text(text)
    except Exception as e:
        print(f"  pymupdf failed for {path.name}: {e}")
        return None


def parse_with_pdfplumber(path: Path) -> pd.DataFrame | None:
    try:
        import pdfplumber
    except Exception:
        return None
    rows = []
    columns = None
    try:
        with pdfplumber.open(path) as pdf:
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                full_text += page_text
                tables = page.extract_tables() or []
                for table in tables:
                    if not table:
                        continue
                    if all(isinstance(c, str) for c in table[0] if c is not None):
                        if columns is None:
                            columns = [(h or "").strip() for h in table[0]]
                        rows.extend([[( c or "").strip() for c in r] for r in table[1:]])
                    else:
                        rows.extend([[(c or "").strip() for c in r] for r in table])
        # Try JSON parse of full text first
        df = _parse_json_text(full_text)
        if df is not None:
            return df
        if rows:
            df = pd.DataFrame(rows)
            if columns and len(columns) == df.shape[1]:
                df.columns = columns
            return df
    except Exception as e:
        print(f"  pdfplumber failed for {path.name}: {e}")
    return None


def parse_text_fallback(path: Path) -> pd.DataFrame | None:
    text = ""
    try:
        import subprocess
        res = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True, text=True, check=True,
        )
        text = res.stdout
    except Exception:
        text = path.read_text(encoding="utf-8", errors="ignore")

    df = _parse_json_text(text)
    if df is not None:
        return df

    rows, columns = [], None
    for line in text.splitlines():
        parts = [p.strip() for p in re.split(r"\s{2,}", line.strip()) if p.strip()]
        if len(parts) <= 1:
            continue
        if columns is None:
            columns = [f"col{i+1}" for i in range(len(parts))]
        rows.append(parts)
    if rows:
        df = pd.DataFrame(rows)
        if columns and len(columns) == df.shape[1]:
            df.columns = columns
        return df
    return None


def main():
    pdfs = sorted(RAW_DIR.glob("*.pdf"))
    if not pdfs:
        print("No HigherGov PDFs found in", RAW_DIR)
        return 1
    for p in pdfs:
        out_name = FILENAME_MAP.get(p.stem, re.sub(r"\W+", "_", p.stem).lower() + ".csv")
        out_path = OUT_DIR / out_name
        print(f"Processing {p.name} -> {out_name}")
        df = parse_with_pymupdf(p)
        if df is None or df.empty:
            df = parse_with_pdfplumber(p)
        if df is None or df.empty:
            df = parse_text_fallback(p)
        if df is None or df.empty:
            print(f"  No data parsed; writing empty schema")
            df = pd.DataFrame(columns=["source_file"])
        df["source_file"] = p.name
        df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"  Wrote {out_path.name} ({len(df)} rows, {len(df.columns)} cols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
