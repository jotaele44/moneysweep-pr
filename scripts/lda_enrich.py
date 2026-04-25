"""
LDA Enrichment Layer — link federal award recipients to their lobbying activity.

Reads entity_master.csv (produced by build_unified_master.py), queries the Senate
LDA API by client_name for each entity, and writes:

  data/staging/processed/entity_lda_enriched.csv   — entity_master + 6 LDA columns
  data/staging/processed/pr_lda_entity_crossref.csv — one row per filing-entity match

LDA is lobbying METADATA, not contract or funding data. It answers:
  "Which of our federal award recipients also lobby the federal government?"

Architecture:
  awards_master → entity_master → [this module] → influence_graph

Columns added to entity_master:
  lda_flag          — 1 if any LDA filings found, 0 otherwise
  lda_total_spend   — sum of all reported lobbying income (USD)
  lda_registrants   — pipe-separated lobbying firms used
  lda_issues        — pipe-separated LDA issue codes lobbied on
  lda_filing_years  — pipe-separated sorted filing years
  lda_filing_count  — total number of filings matched

Usage:
  python3 scripts/lda_enrich.py
  python3 scripts/lda_enrich.py --top-n 200
  python3 scripts/lda_enrich.py --force          # ignore cached entity queries
  python3 scripts/lda_enrich.py --api-key TOKEN
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LDA_BASE      = "https://lda.senate.gov/api/v1"
PAGE_SIZE     = 25        # LDA API max per page
PAGE_SLEEP    = 0.5       # seconds between pages (120 req/min with token)
QUERY_SLEEP   = 0.6       # seconds between entity queries
MAX_RETRIES   = 3
RETRY_BACKOFF = [10, 30, 60]
TOP_N_DEFAULT = 500       # top entities by total_obligated to query

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF", "SA", "SRL",
    "HOSPITAL", "HEALTH", "CENTER", "CENTRE",
}

CROSSREF_COLUMNS = [
    "entity_key", "canonical_name", "total_awards_obligated", "award_count",
    "filing_uuid", "filing_year", "filing_type", "period_of_report",
    "registrant_name", "registrant_state", "client_name", "client_state",
    "income", "expenses", "general_issue_codes", "issue_descriptions",
    "lobbyist_names",
]

LDA_ENRICH_COLUMNS = [
    "lda_flag", "lda_total_spend", "lda_registrants",
    "lda_issues", "lda_filing_years", "lda_filing_count",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _token_overlap(a: str, b: str) -> float:
    """Fraction of tokens in `a` that appear in `b`."""
    ta = set(a.split())
    tb = set(b.split())
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def _session(api_key: str | None) -> requests.Session:
    s = requests.Session()
    headers = {
        "User-Agent": "ContractSweeper/1.0 (PR federal spending research)",
        "Accept":     "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Token {api_key}"
    s.headers.update(headers)
    return s


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------

def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.debug(f"  HTTP {resp.status_code} for {params}: {resp.text[:200]}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt + 1} failed ({exc}) — retry in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _fetch_filings_for_entity(
    session: requests.Session,
    canonical_name: str,
    entity_key: str,
    logger,
) -> list[dict]:
    """Fetch all LDA filings where client_name matches the entity."""
    url  = f"{LDA_BASE}/filings/"
    page = 1
    records = []

    while True:
        params = {
            "client_name": canonical_name,
            "page_size":   PAGE_SIZE,
            "page":        page,
        }
        data = _get(session, url, params, logger)
        if data is None:
            break

        results = data.get("results") or []
        for rec in results:
            client_name = (rec.get("client") or {}).get("name") or ""
            norm_client = _normalize(client_name)
            # Accept if token overlap ≥ 80% in both directions
            fwd = _token_overlap(entity_key, norm_client)
            rev = _token_overlap(norm_client, entity_key)
            if fwd >= 0.80 or rev >= 0.80:
                records.append(rec)

        if not data.get("next"):
            break
        page += 1

    return records


# ---------------------------------------------------------------------------
# Flatten one LDA filing record
# ---------------------------------------------------------------------------

def _flatten(rec: dict) -> dict:
    registrant = rec.get("registrant") or {}
    client     = rec.get("client") or {}

    activities = rec.get("lobbying_activities") or []
    issue_codes, issue_descs, lobbyist_names = [], [], []
    for act in activities:
        code = act.get("general_issue_code_display") or act.get("general_issue_code") or ""
        if code and code not in issue_codes:
            issue_codes.append(code)
        desc = (act.get("description") or "").strip()
        if desc:
            issue_descs.append(desc[:120])
        for lob in act.get("lobbyists") or []:
            name = (lob.get("lobbyist", {}) or {}).get("name") or lob.get("name") or ""
            if name and name not in lobbyist_names:
                lobbyist_names.append(name)

    reg_address = registrant.get("address") or {}
    cli_address = client.get("address") or {}

    return {
        "filing_uuid":        rec.get("filing_uuid", ""),
        "filing_year":        rec.get("filing_year", ""),
        "filing_type":        rec.get("filing_type", ""),
        "period_of_report":   rec.get("period_of_report", ""),
        "registrant_name":    registrant.get("name", ""),
        "registrant_state":   registrant.get("state") or reg_address.get("state") or "",
        "client_name":        client.get("name", ""),
        "client_state":       client.get("state") or cli_address.get("state") or "",
        "income":             rec.get("income", ""),
        "expenses":           rec.get("expenses", ""),
        "general_issue_codes": "|".join(issue_codes[:10]),
        "issue_descriptions":  "|".join(issue_descs[:5]),
        "lobbyist_names":      "|".join(lobbyist_names[:15]),
    }


# ---------------------------------------------------------------------------
# Core run
# ---------------------------------------------------------------------------

def run(root: Path = None, api_key: str | None = None,
        top_n: int = TOP_N_DEFAULT, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)

    processed_dir = root / "data" / "staging" / "processed"
    cache_dir     = root / "data" / "staging" / "raw" / "lda" / "entity_queries"
    cache_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("lda_enrich", log_dir=root / "data" / "logs")

    # Resolve API key
    if not api_key:
        api_key = os.environ.get("LDA_API_KEY", "").strip() or None
    if not api_key:
        logger.warning("  LDA_API_KEY not set — queries will use unauthenticated rate limits")

    # ------------------------------------------------------------------
    # Load entity_master
    # ------------------------------------------------------------------
    entity_path = processed_dir / "entity_master.csv"
    if not entity_path.exists():
        logger.error(f"  entity_master.csv not found at {entity_path}")
        logger.error("  Run build_unified_master.py first.")
        return {"entities_queried": 0, "entities_matched": 0, "total_spend": 0.0, "status": "NO_INPUT"}

    df_entities = pd.read_csv(entity_path, dtype=str, low_memory=False)
    logger.info(f"  Loaded entity_master: {len(df_entities):,} entities")

    # Sort by total_obligated descending, take top N
    df_entities["_oblig_num"] = pd.to_numeric(df_entities.get("total_obligated", pd.Series(dtype=str)), errors="coerce").fillna(0.0)
    df_entities = df_entities.sort_values("_oblig_num", ascending=False).head(top_n).reset_index(drop=True)
    logger.info(f"  Querying top {len(df_entities):,} entities by total obligation")

    session = _session(api_key)
    crossref_rows: list[dict] = []
    enrich_rows:   list[dict] = []
    entities_matched = 0

    for idx, ent in df_entities.iterrows():
        entity_key     = str(ent.get("entity_key", "") or "")
        canonical_name = str(ent.get("canonical_name", "") or "")
        if not canonical_name.strip():
            continue

        cache_file = cache_dir / f"{entity_key[:80].replace('/', '_')}.json"

        # Load from cache or fetch
        if not force and cache_file.exists():
            try:
                with open(cache_file) as fh:
                    raw_filings = json.load(fh)
            except Exception:
                raw_filings = []
        else:
            raw_filings = _fetch_filings_for_entity(session, canonical_name, entity_key, logger)
            try:
                with open(cache_file, "w") as fh:
                    json.dump(raw_filings, fh)
            except Exception:
                pass
            time.sleep(QUERY_SLEEP)

        if not raw_filings:
            enrich_rows.append({
                "entity_key":     entity_key,
                "lda_flag":       0,
                "lda_total_spend": 0.0,
                "lda_registrants": "",
                "lda_issues":      "",
                "lda_filing_years": "",
                "lda_filing_count": 0,
            })
            continue

        # Aggregate across filings
        total_spend   = 0.0
        registrants   = []
        issues        = []
        filing_years  = set()

        for rec in raw_filings:
            flat = _flatten(rec)
            income = flat.get("income") or 0
            try:
                total_spend += float(income)
            except (ValueError, TypeError):
                pass

            reg = flat.get("registrant_name", "")
            if reg and reg not in registrants:
                registrants.append(reg)

            for code in (flat.get("general_issue_codes") or "").split("|"):
                code = code.strip()
                if code and code not in issues:
                    issues.append(code)

            yr = str(flat.get("filing_year", "")).strip()
            if yr:
                filing_years.add(yr)

            # Add to crossref
            crossref_rows.append({
                "entity_key":            entity_key,
                "canonical_name":        canonical_name,
                "total_awards_obligated": float(ent.get("_oblig_num", 0)),
                "award_count":           ent.get("award_count", ""),
                **flat,
            })

        entities_matched += 1
        enrich_rows.append({
            "entity_key":       entity_key,
            "lda_flag":         1,
            "lda_total_spend":  round(total_spend, 2),
            "lda_registrants":  "|".join(registrants[:10]),
            "lda_issues":       "|".join(issues[:20]),
            "lda_filing_years": "|".join(sorted(filing_years)),
            "lda_filing_count": len(raw_filings),
        })

        if (idx + 1) % 50 == 0:
            logger.info(f"  Progress: {idx + 1:,}/{len(df_entities):,} entities queried, "
                        f"{entities_matched:,} with LDA filings")

    session.close()

    # ------------------------------------------------------------------
    # Build entity_lda_enriched.csv
    # ------------------------------------------------------------------
    df_enrich = pd.DataFrame(enrich_rows)

    df_enriched = df_entities.drop(columns=["_oblig_num"], errors="ignore")
    if not df_enrich.empty:
        df_enriched = df_enriched.merge(
            df_enrich[["entity_key"] + LDA_ENRICH_COLUMNS],
            on="entity_key",
            how="left",
        )
        df_enriched["lda_flag"]        = df_enriched["lda_flag"].fillna(0).astype(int)
        df_enriched["lda_total_spend"] = df_enriched["lda_total_spend"].fillna(0.0)
        df_enriched["lda_filing_count"] = df_enriched["lda_filing_count"].fillna(0).astype(int)
        for col in ["lda_registrants", "lda_issues", "lda_filing_years"]:
            df_enriched[col] = df_enriched[col].fillna("")
    else:
        for col in LDA_ENRICH_COLUMNS:
            df_enriched[col] = "" if col not in ("lda_flag", "lda_total_spend", "lda_filing_count") else 0

    enriched_path = processed_dir / "entity_lda_enriched.csv"
    df_enriched.to_csv(enriched_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {enriched_path.name} ({len(df_enriched):,} entities)")

    # ------------------------------------------------------------------
    # Build pr_lda_entity_crossref.csv
    # ------------------------------------------------------------------
    if crossref_rows:
        df_crossref = pd.DataFrame(crossref_rows)
        for col in CROSSREF_COLUMNS:
            if col not in df_crossref.columns:
                df_crossref[col] = ""
        df_crossref = df_crossref[CROSSREF_COLUMNS]
    else:
        df_crossref = pd.DataFrame(columns=CROSSREF_COLUMNS)

    crossref_path = processed_dir / "pr_lda_entity_crossref.csv"
    df_crossref.to_csv(crossref_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {crossref_path.name} ({len(df_crossref):,} filing matches)")

    total_spend = float(df_enriched["lda_total_spend"].sum()) if not df_enriched.empty else 0.0

    logger.info("=" * 60)
    logger.info("LDA ENRICHMENT SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Entities queried:   {len(df_entities):,}")
    logger.info(f"  Entities matched:   {entities_matched:,} ({entities_matched / max(len(df_entities), 1):.1%})")
    logger.info(f"  Total lobby spend:  ${total_spend:,.0f}")
    logger.info(f"  Filing matches:     {len(df_crossref):,}")

    if entities_matched > 0:
        top = (
            df_enriched[df_enriched["lda_flag"] == 1]
            .sort_values("lda_total_spend", ascending=False)
            .head(10)
        )
        logger.info("  Top lobbying award recipients:")
        for _, row in top.iterrows():
            logger.info(
                f"    {str(row.get('canonical_name', ''))[:50]:<50}  "
                f"${float(row.get('lda_total_spend', 0)):>12,.0f}  "
                f"[{str(row.get('lda_issues', ''))[:40]}]"
            )

    return {
        "entities_queried": len(df_entities),
        "entities_matched": entities_matched,
        "total_spend":      total_spend,
        "filing_matches":   len(df_crossref),
        "enriched_path":    str(enriched_path),
        "crossref_path":    str(crossref_path),
        "status":           "OK",
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich award recipients with LDA lobbying data (client_name lookup)"
    )
    parser.add_argument("--api-key", default=None,
                        help="LDA API token (default: LDA_API_KEY env var)")
    parser.add_argument("--top-n", type=int, default=TOP_N_DEFAULT,
                        help=f"Top N entities by obligation to query (default: {TOP_N_DEFAULT})")
    parser.add_argument("--force", action="store_true",
                        help="Ignore cached entity query results")
    args = parser.parse_args()

    result = run(api_key=args.api_key, top_n=args.top_n, force=args.force)
    print(f"\nLDA enrichment complete.")
    print(f"  Entities queried:  {result['entities_queried']:,}")
    print(f"  Entities matched:  {result['entities_matched']:,}")
    print(f"  Total lobby spend: ${result['total_spend']:,.0f}")
    print(f"  Filing matches:    {result['filing_matches']:,}")
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
