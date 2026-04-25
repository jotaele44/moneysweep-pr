"""
Download OFAC Specially Designated Nationals (SDN) list and cross-reference
against the unified awards master to flag sanctioned entities receiving
federal contracts or grants tied to Puerto Rico.

Source: US Treasury Office of Foreign Assets Control
URL:    https://www.treasury.gov/ofac/downloads/sdn.xml

Outputs:
  data/staging/processed/pr_ofac_sdn.csv      — all SDN entities
  data/staging/processed/pr_ofac_matches.csv  — awards master entities matched to SDN

Usage:
  python3 scripts/download_ofac.py [--force]
"""

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

OFAC_SDN_XML  = "https://www.treasury.gov/ofac/downloads/sdn.xml"
MAX_RETRIES   = 3
RETRY_BACKOFF = [5, 15, 30]

SDN_COLUMNS = ["uid", "name", "sdn_type", "programs", "aka_names"]

MATCH_COLUMNS = [
    "normalized_name", "recipient_name", "total_awards_obligated",
    "award_count", "source_dataset", "sdn_uid", "sdn_name",
    "sdn_type", "sdn_programs",
]

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF", "SA", "SRL",
    "HOSPITAL", "HEALTH", "CENTER", "CENTRE",
}


def _normalize(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    n = str(name).upper()
    n = _STRIP_RE.sub(" ", n)
    n = _SPACE_RE.sub(" ", n).strip()
    tokens = n.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR sanctions research)",
        "Accept":     "application/xml,text/xml",
    })
    return s


def _download_xml(session: requests.Session, url: str, logger) -> bytes | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=120)
            if 400 <= resp.status_code < 500:
                logger.error(f"  HTTP {resp.status_code}: {url}")
                return None
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _parse_sdn_xml(content: bytes, logger) -> pd.DataFrame:
    logger.info("  Parsing SDN XML...")
    NS = "http://tempuri.org/sdnList.xsd"

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        logger.error(f"  XML parse error: {exc}")
        return pd.DataFrame(columns=SDN_COLUMNS)

    # Detect the actual namespace from the root element tag (robust against NS changes)
    _actual_ns = root.tag.split("}")[0][1:] if root.tag.startswith("{") else ""

    def _find(el, tag):
        result = el.find(tag)
        if result is None:
            result = el.find(f"{{{NS}}}{tag}")
        if result is None and _actual_ns and _actual_ns != NS:
            result = el.find(f"{{{_actual_ns}}}{tag}")
        return result

    def _findall(el, path):
        results = el.findall(path)
        ns_path = "/".join(
            f"{{{NS}}}{p}" if not p.startswith("{") else p
            for p in path.split("/")
        )
        if not results:
            results = el.findall(ns_path)
        if not results and _actual_ns and _actual_ns != NS:
            ns_path2 = "/".join(
                f"{{{_actual_ns}}}{p}" if not p.startswith("{") else p
                for p in path.split("/")
            )
            results = el.findall(ns_path2)
        return results

    def _text(el, tag):
        child = _find(el, tag)
        return child.text.strip() if child is not None and child.text else ""

    entries = root.findall(".//sdnEntry")
    if not entries:
        entries = root.findall(f".//{{{NS}}}sdnEntry")
    if not entries and _actual_ns and _actual_ns != NS:
        entries = root.findall(f".//{{{_actual_ns}}}sdnEntry")
        if entries:
            logger.info(f"  Found {len(entries):,} entries using detected namespace: {_actual_ns}")

    rows = []
    for entry in entries:
        uid      = _text(entry, "uid")
        last     = _text(entry, "lastName")
        first    = _text(entry, "firstName")
        name     = f"{last}, {first}".strip(", ") if first else last
        sdn_type = _text(entry, "sdnType")

        prog_els = (
            entry.findall(".//program")
            or entry.findall(f".//{{{NS}}}program")
            or (entry.findall(f".//{{{_actual_ns}}}program") if _actual_ns and _actual_ns != NS else [])
        )
        programs = "|".join(sorted({p.text.strip() for p in prog_els if p.text}))

        aka_els = (
            entry.findall(".//aka/lastName") + entry.findall(".//aka/firstName")
            + entry.findall(f".//{{{NS}}}aka/{{{NS}}}lastName")
            + entry.findall(f".//{{{NS}}}aka/{{{NS}}}firstName")
        )
        if not aka_els and _actual_ns and _actual_ns != NS:
            aka_els = (
                entry.findall(f".//{{{_actual_ns}}}aka/{{{_actual_ns}}}lastName")
                + entry.findall(f".//{{{_actual_ns}}}aka/{{{_actual_ns}}}firstName")
            )
        akas = "|".join(sorted({el.text.strip() for el in aka_els if el.text}))

        rows.append({"uid": uid, "name": name, "sdn_type": sdn_type,
                     "programs": programs, "aka_names": akas})

    logger.info(f"  Parsed {len(rows):,} SDN entries")
    return pd.DataFrame(rows, columns=SDN_COLUMNS)


def _crossref(df_sdn: pd.DataFrame, awards_path: Path, logger) -> pd.DataFrame:
    if not awards_path.exists():
        logger.warning("  Awards master not found — skipping crossref")
        return pd.DataFrame(columns=MATCH_COLUMNS)

    logger.info("  Loading awards master for crossref...")
    awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
    awards["_amount"] = pd.to_numeric(awards["obligated_amount"], errors="coerce").fillna(0)
    awards = awards[awards["recipient_name"].notna()].copy()
    awards["_norm"] = awards["recipient_name"].apply(_normalize)
    awards = awards[awards["_norm"] != ""]

    entity_agg = (
        awards.groupby("_norm")
        .agg(
            recipient_name         = ("recipient_name",  "first"),
            total_awards_obligated = ("_amount",         "sum"),
            award_count            = ("award_id",        "nunique"),
            source_dataset         = ("source_dataset",  lambda x: "|".join(sorted(x.dropna().unique()))),
        )
        .reset_index()
        .rename(columns={"_norm": "normalized_name"})
    )

    # Build SDN name → row index (primary name + all AKAs)
    sdn_index: dict[str, dict] = {}
    for _, row in df_sdn.iterrows():
        all_names = [row["name"]] + [n for n in row["aka_names"].split("|") if n]
        for raw in all_names:
            norm = _normalize(raw)
            if norm:
                sdn_index.setdefault(norm, dict(row))

    matches = []
    for _, ent in entity_agg.iterrows():
        hit = sdn_index.get(ent["normalized_name"])
        if hit:
            matches.append({
                "normalized_name":       ent["normalized_name"],
                "recipient_name":        ent["recipient_name"],
                "total_awards_obligated": ent["total_awards_obligated"],
                "award_count":           ent["award_count"],
                "source_dataset":        ent["source_dataset"],
                "sdn_uid":               hit["uid"],
                "sdn_name":              hit["name"],
                "sdn_type":              hit["sdn_type"],
                "sdn_programs":          hit["programs"],
            })

    df = pd.DataFrame(matches, columns=MATCH_COLUMNS) if matches else pd.DataFrame(columns=MATCH_COLUMNS)
    logger.info(f"  {len(df):,} awards-master entities matched to SDN list")
    return df


# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "ofac"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path    = raw_dir / "sdn.xml"
    sdn_path    = out_dir / "pr_ofac_sdn.csv"
    match_path  = out_dir / "pr_ofac_matches.csv"
    awards_path = out_dir / "pr_all_awards_master.csv"

    logger  = setup_logging("download_ofac")
    session = _session()

    if not force and raw_path.exists():
        logger.info(f"  SDN XML cached — loading {raw_path.name}")
        content = raw_path.read_bytes()
    else:
        logger.info("  Downloading OFAC SDN list...")
        content = _download_xml(session, OFAC_SDN_XML, logger)
        if content is None:
            session.close()
            return {"sdn_rows": 0, "match_rows": 0, "status": "DOWNLOAD_FAILED"}
        raw_path.write_bytes(content)
        logger.info(f"  Cached {raw_path.name} ({len(content):,} bytes)")

    session.close()

    df_sdn = _parse_sdn_xml(content, logger)
    df_sdn.to_csv(sdn_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {sdn_path.name} ({len(df_sdn):,} entries)")

    df_matches = _crossref(df_sdn, awards_path, logger)
    df_matches.to_csv(match_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {match_path.name} ({len(df_matches):,} matches)")

    entity_ct = int((df_sdn["sdn_type"] == "Entity").sum())
    indiv_ct  = int((df_sdn["sdn_type"] == "Individual").sum())

    logger.info("=" * 60)
    logger.info("OFAC SDN SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total SDN entries:     {len(df_sdn):,}")
    logger.info(f"  Entity type:           {entity_ct:,}")
    logger.info(f"  Individual type:       {indiv_ct:,}")
    logger.info(f"  Awards master matches: {len(df_matches):,}")

    if not df_matches.empty:
        total_at_risk = float(
            pd.to_numeric(df_matches["total_awards_obligated"], errors="coerce").sum()
        )
        logger.info(f"  Total obligated (matched): ${total_at_risk:,.0f}")
        logger.info("  Matched entities:")
        for _, row in df_matches.head(10).iterrows():
            logger.info(f"    {str(row['recipient_name'])[:50]:<50}  {row['sdn_programs']}")

    return {
        "sdn_rows":   len(df_sdn),
        "match_rows": len(df_matches),
        "status":     "OK" if len(df_sdn) > 0 else "EMPTY",
        "sdn_path":   str(sdn_path),
        "match_path": str(match_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download OFAC SDN list and crossref against PR awards")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nOFAC complete: {result['sdn_rows']:,} SDN entries, "
          f"{result['match_rows']:,} awards master matches.")
    return 0 if result["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
