"""Geographic attribution for Puerto Rico tabular data.

Attaches canonical geo columns to a dataframe so rows from any of the 82
registry sources become geographically queryable on a common schema. Geo
attribution is enrichment, not a filter — rows that cannot be matched are
preserved with null geo columns and ``geo_attribution_confidence='unknown'``.

Canonical geo columns attached:

    geo_municipality_code         5-digit county-FIPS, e.g. '72127' San Juan
    geo_municipality_name         Canonical English name
    geo_county_fips               Same as municipality code in PR
    geo_zip                       From source if available, else null
    geo_lat / geo_lon             From source if available, else null
    geo_attribution_source        Input column the match came from
    geo_attribution_confidence    exact_fips | exact_name | normalized_name
                                  | fuzzy_name | unknown

Reference data: ``data/reference/pr_municipalities.csv`` (78 rows).
"""

from __future__ import annotations

import functools
import re
import unicodedata
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = "data/reference/pr_municipalities.csv"

GEO_COLUMNS = (
    "geo_municipality_code",
    "geo_municipality_name",
    "geo_county_fips",
    "geo_zip",
    "geo_lat",
    "geo_lon",
    "geo_attribution_source",
    "geo_attribution_confidence",
)

# Priority order for picking the best available geo input column. Higher
# entries are preferred. The first entry that exists in the dataframe and
# has a non-empty value for a given row wins.
GEO_INPUT_PRIORITY = (
    "geo_municipality_code",
    "municipality_code",
    "county_fips",
    "geo_municipality_name",
    "municipality",
    "municipio",
    "pop_county",
    "place_of_performance_county",
    "place_of_performance_county_name",
    "place_of_performance_city",
    "recipient_city_name",
    "primary_place_of_performance_city_name",
    "city",
)

ZIP_INPUT_PRIORITY = (
    "geo_zip",
    "zip",
    "zip_code",
    "place_of_performance_zip",
    "place_of_performance_zip5",
    "place_of_performance_zip4",
    "primary_place_of_performance_zip",
    "recipient_zip",
)

LAT_INPUT_PRIORITY = ("geo_lat", "lat", "latitude", "place_of_performance_latitude")
LON_INPUT_PRIORITY = ("geo_lon", "lon", "longitude", "place_of_performance_longitude")

_PREFIX_RE = re.compile(r"^(MUNICIPIO\s+DE|MUNICIPALITY\s+OF|CIUDAD\s+DE|CITY\s+OF)\s+")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9 ]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _normalize_pr_name(value: object) -> str:
    """Normalize a place-name string for joining against the reference table.

    Strips accents, uppercases, removes "Municipio de" / "Municipality of"
    prefixes, drops non-alphanumeric characters, collapses whitespace.
    Returns an empty string for null / empty input.
    """
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    s = str(value).strip()
    if not s:
        return ""
    s = _strip_accents(s).upper()
    s = _PREFIX_RE.sub("", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def _normalize_fips(value: object) -> str:
    """Normalize a FIPS value to a 5-digit zero-padded string.

    Accepts ints, floats, strings with leading zeros, or strings like
    '72127.0'. Returns empty string for null / non-numeric / wrong-prefix
    inputs (PR FIPS codes always start with '72').
    """
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    if not s.isdigit():
        return ""
    if len(s) > 5:
        return ""
    s = s.zfill(5)
    if not s.startswith("72"):
        return ""
    return s


@functools.lru_cache(maxsize=4)
def _load_reference(root_str: str) -> dict[str, dict[str, str]]:
    """Load the PR municipality reference table.

    Returns a dict with two indexes:
        by_fips:    {municipality_code: row_dict}
        by_alias:   {normalized_alias: row_dict}  (includes canonical name)

    If the reference file is absent (e.g. tests using a synthetic root),
    returns empty indexes so attribution becomes a safe no-op.
    """
    root = Path(root_str)
    path = root / REFERENCE_PATH
    if not path.exists():
        return {"by_fips": {}, "by_alias": {}}
    df = pd.read_csv(path, dtype=str).fillna("")
    by_fips: dict[str, dict[str, str]] = {}
    by_alias: dict[str, dict[str, str]] = {}
    for row in df.to_dict(orient="records"):
        code = _normalize_fips(row["municipality_code"])
        if not code:
            continue
        record = {
            "geo_municipality_code": code,
            "geo_municipality_name": row["canonical_name"],
            "geo_county_fips": row["county_fips"] or code,
        }
        by_fips[code] = record
        # Canonical English + Spanish names are exact-name candidates.
        for name in (row["canonical_name"], row["canonical_name_es"]):
            key = _normalize_pr_name(name)
            if key:
                by_alias.setdefault(key, record)
        # Alias-pipe list contributes normalized_name candidates.
        for alias in (row.get("aliases") or "").split("|"):
            key = _normalize_pr_name(alias)
            if key:
                by_alias.setdefault(key, record)
    return {"by_fips": by_fips, "by_alias": by_alias}


def _pick_existing(columns: list[str], priority: tuple[str, ...]) -> str | None:
    """Return the first name in `priority` that exists in `columns`, else None."""
    cset = set(columns)
    for name in priority:
        if name in cset:
            return name
    return None


def _resolve_row(
    fips_val: str,
    name_val_raw: object,
    *,
    by_fips: dict,
    by_alias: dict,
    fips_input_col: str | None,
    name_input_col: str | None,
) -> tuple[dict | None, str, str]:
    """Resolve a single row's geo. Returns (record_or_None, source_col, confidence)."""
    # FIPS direct hit beats name.
    if fips_val:
        rec = by_fips.get(fips_val)
        if rec is not None:
            return rec, fips_input_col or "", "exact_fips"
    # Name match (exact canonical / normalized alias).
    if name_val_raw is None:
        return None, "", "unknown"
    raw_str = (
        ""
        if (isinstance(name_val_raw, float) and pd.isna(name_val_raw))
        else str(name_val_raw).strip()
    )
    if not raw_str:
        return None, "", "unknown"
    # Exact match on the raw (case/accents) form first.
    exact_key = _normalize_pr_name(raw_str)
    if exact_key in by_alias:
        # Distinguish "exact_name" (input already matched canonical exactly,
        # case/diacritics aside) from "normalized_name" (prefix/punct stripped).
        upper_raw = _strip_accents(raw_str).upper().strip()
        if upper_raw == exact_key:
            return by_alias[exact_key], name_input_col or "", "exact_name"
        return by_alias[exact_key], name_input_col or "", "normalized_name"
    return None, name_input_col or "", "unknown"


def attribute_geo(
    df: pd.DataFrame,
    *,
    source_id: str | None = None,
    root: Path | None = None,
) -> pd.DataFrame:
    """Attach canonical geo columns to df. Idempotent. Never drops rows.

    If the dataframe already has a populated ``geo_municipality_code`` column,
    rows with non-empty values are left alone (only blank rows are attempted
    again). The function always returns a dataframe with every column in
    ``GEO_COLUMNS`` present.
    """
    if df is None or len(df) == 0:
        out = df.copy() if df is not None else pd.DataFrame()
        for col in GEO_COLUMNS:
            if col not in out.columns:
                out[col] = pd.Series(dtype=object)
        return out

    out = df.copy()
    root_str = str(root or REPO_ROOT)
    ref = _load_reference(root_str)
    by_fips = ref["by_fips"]
    by_alias = ref["by_alias"]

    columns = list(out.columns)
    fips_col = _pick_existing(
        columns, ("geo_municipality_code", "municipality_code", "county_fips")
    )
    name_col = _pick_existing(columns, GEO_INPUT_PRIORITY[3:])  # skip the fips-ish names
    zip_col = _pick_existing(columns, ZIP_INPUT_PRIORITY)
    lat_col = _pick_existing(columns, LAT_INPUT_PRIORITY)
    lon_col = _pick_existing(columns, LON_INPUT_PRIORITY)

    # Ensure every output column exists.
    for col in GEO_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    # Resolve row-by-row. Pre-extract input series for speed.
    fips_series = (
        out[fips_col].map(_normalize_fips)
        if fips_col
        else pd.Series([""] * len(out), index=out.index)
    )
    name_series = out[name_col] if name_col else pd.Series([None] * len(out), index=out.index)

    existing_code = out["geo_municipality_code"].astype(str).fillna("")
    existing_conf = out["geo_attribution_confidence"].astype(str).fillna("")

    codes: list[str] = []
    names: list[str] = []
    county_fips: list[str] = []
    src_cols: list[str] = []
    confs: list[str] = []

    for idx in range(len(out)):
        # Idempotency: if this row already has a code and a non-unknown
        # confidence, keep it as-is.
        prior_code = existing_code.iloc[idx].strip()
        prior_conf = existing_conf.iloc[idx].strip()
        if prior_code and prior_conf and prior_conf != "unknown":
            codes.append(prior_code)
            names.append(out["geo_municipality_name"].iloc[idx])
            county_fips.append(out["geo_county_fips"].iloc[idx] or prior_code)
            src_cols.append(out["geo_attribution_source"].iloc[idx])
            confs.append(prior_conf)
            continue

        rec, src_col, conf = _resolve_row(
            fips_val=fips_series.iloc[idx],
            name_val_raw=name_series.iloc[idx],
            by_fips=by_fips,
            by_alias=by_alias,
            fips_input_col=fips_col,
            name_input_col=name_col,
        )
        if rec is None:
            codes.append("")
            names.append("")
            county_fips.append("")
            src_cols.append(src_col)
            confs.append("unknown")
        else:
            codes.append(rec["geo_municipality_code"])
            names.append(rec["geo_municipality_name"])
            county_fips.append(rec["geo_county_fips"])
            src_cols.append(src_col)
            confs.append(conf)

    out["geo_municipality_code"] = codes
    out["geo_municipality_name"] = names
    out["geo_county_fips"] = county_fips
    out["geo_attribution_source"] = src_cols
    out["geo_attribution_confidence"] = confs

    # Pass-through optional spatial fields. Never overwrite a non-empty value.
    if zip_col:
        zip_in = out[zip_col].astype(str).fillna("")
        existing_zip = out["geo_zip"].astype(str).fillna("")
        out["geo_zip"] = existing_zip.where(existing_zip != "", zip_in)
    if lat_col:
        lat_in = out[lat_col]
        existing_lat = out["geo_lat"]
        out["geo_lat"] = existing_lat.where(existing_lat.astype(str).fillna("") != "", lat_in)
    if lon_col:
        lon_in = out[lon_col]
        existing_lon = out["geo_lon"]
        out["geo_lon"] = existing_lon.where(existing_lon.astype(str).fillna("") != "", lon_in)

    return out


def attribution_summary(df: pd.DataFrame) -> dict[str, int]:
    """Return a dict summarizing geo attribution status of a dataframe."""
    if "geo_attribution_confidence" not in df.columns:
        return {"total": int(len(df)), "attributed": 0, "unknown": int(len(df))}
    conf = df["geo_attribution_confidence"].astype(str).fillna("")
    counts = conf.value_counts().to_dict()
    total = int(len(df))
    unknown = int(counts.get("unknown", 0)) + int((conf == "").sum())
    return {
        "total": total,
        "attributed": total - unknown,
        "unknown": unknown,
        "exact_fips": int(counts.get("exact_fips", 0)),
        "exact_name": int(counts.get("exact_name", 0)),
        "normalized_name": int(counts.get("normalized_name", 0)),
        "fuzzy_name": int(counts.get("fuzzy_name", 0)),
    }
