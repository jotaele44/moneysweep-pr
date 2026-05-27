"""
Cross-reference political-finance datasets against the unified awards master.

Identifies Puerto Rico entities that appear as both federal award recipients and
participants in political-finance activity (FEC campaign contributions, LDA lobbying).

Two crossref families, one shared normalisation pipeline:

  FEC crossref   — entities in both pr_all_awards_master.csv and pr_fec_contributions.csv
  Lobbying crossref — entities in both pr_all_awards_master.csv and pr_lda_filings.csv

Outputs:
  data/staging/processed/pr_fec_crossref.csv
  data/staging/processed/pr_lobbying_crossref.csv

Usage:
  python3 scripts/analyze_political_crossref.py          # run both
  python3 scripts/analyze_political_crossref.py --fec    # FEC only
  python3 scripts/analyze_political_crossref.py --lda    # lobbying only
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from contract_sweeper.runtime.alias_overrides import apply as apply_override
from contract_sweeper.runtime.alias_overrides import load_overrides
from scripts.config import PROJECT_ROOT, setup_logging


# ---------------------------------------------------------------------------
# Shared name normalisation
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "PC",
    "PLLC", "DBA", "THE", "AND", "OF", "SA", "SL", "SRL",
}

_OVERRIDES = load_overrides()


def _normalize(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    n = str(name).upper()
    n = _STRIP_RE.sub(" ", n)
    n = _SPACE_RE.sub(" ", n).strip()
    tokens = n.split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    local = " ".join(tokens)
    canonical, overridden = apply_override(local, _OVERRIDES)
    return canonical if overridden else local


def _year_range(series: pd.Series) -> str:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return ""
    lo, hi = int(vals.min()), int(vals.max())
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _merge_pipe(series: pd.Series, limit: int) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for cell in series.dropna():
        for part in str(cell).split("|"):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                out.append(part)
                if len(out) >= limit:
                    return "|".join(out)
    return "|".join(out)


# ---------------------------------------------------------------------------
# Awards index (shared by both crossrefs)
# ---------------------------------------------------------------------------

def _build_award_index(awards: pd.DataFrame) -> pd.DataFrame:
    awards = awards.copy()
    awards["_norm"] = awards["recipient_name"].apply(_normalize)
    awards["_amt"] = pd.to_numeric(awards["obligated_amount"], errors="coerce").fillna(0)
    return (
        awards[awards["_norm"] != ""]
        .groupby("_norm")
        .agg(
            award_recipient_name=("recipient_name", "first"),
            total_awards_obligated=("_amt", "sum"),
            award_count=("award_id", "nunique"),
            award_datasets=("source_dataset", lambda x: "|".join(sorted(x.dropna().unique()))),
            award_years=("fiscal_year", _year_range),
        )
        .reset_index()
    )


# ---------------------------------------------------------------------------
# FEC crossref
# ---------------------------------------------------------------------------

def build_fec_crossref(root: Path | None = None) -> dict:
    """Cross-reference FEC campaign contributions against the awards master."""
    root = Path(root) if root is not None else PROJECT_ROOT
    processed_dir = root / "data" / "staging" / "processed"
    logger = setup_logging("analyze_political_crossref.fec")

    awards_path = processed_dir / "pr_all_awards_master.csv"
    fec_path = processed_dir / "pr_fec_contributions.csv"
    out_path = processed_dir / "pr_fec_crossref.csv"

    if not awards_path.exists():
        logger.error(f"  Awards master not found: {awards_path}")
        return {"rows": 0, "status": "MISSING_AWARDS"}
    if not fec_path.exists():
        logger.error(f"  FEC contributions not found: {fec_path}")
        return {"rows": 0, "status": "MISSING_FEC"}

    awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
    fec = pd.read_csv(fec_path, dtype=str, low_memory=False)
    logger.info(f"  {len(awards):,} award rows · {len(fec):,} FEC contribution rows")

    award_index = _build_award_index(awards)

    fec["_norm"] = fec["contributor_name"].apply(_normalize)
    fec["_amt"] = pd.to_numeric(fec["contribution_receipt_amount"], errors="coerce").fillna(0)
    fec_index = (
        fec[fec["_norm"] != ""]
        .groupby("_norm")
        .agg(
            fec_contributor_name=("contributor_name", "first"),
            total_contributions=("_amt", "sum"),
            contribution_count=("contribution_receipt_amount", "count"),
            committees_funded=("committee_name", lambda x: "|".join(sorted(x.dropna().unique())[:10])),
            candidates_funded=("candidate_name", lambda x: "|".join(sorted(x[x != ""].dropna().unique())[:10])),
            latest_contribution=("contribution_receipt_date", "max"),
            earliest_contribution=("contribution_receipt_date", "min"),
        )
        .reset_index()
    )

    merged = award_index.merge(fec_index, on="_norm", how="inner")
    if merged.empty:
        logger.warning("  No FEC cross-reference matches found.")
        merged = pd.DataFrame(columns=[
            "normalized_name", "award_recipient_name", "fec_contributor_name",
            "total_awards_obligated", "total_contributions", "award_count",
            "contribution_count", "award_datasets", "award_years", "committees_funded",
            "candidates_funded", "latest_contribution", "earliest_contribution",
        ])
    else:
        merged = merged.rename(columns={"_norm": "normalized_name"})
        merged = merged.sort_values("total_awards_obligated", ascending=False)

    merged.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  FEC crossref: {len(merged):,} matched entities → {out_path.name}")
    return {"rows": len(merged), "status": "OK" if not merged.empty else "EMPTY", "path": str(out_path)}


# ---------------------------------------------------------------------------
# Lobbying crossref
# ---------------------------------------------------------------------------

def _normalized_name_set(df: pd.DataFrame, columns: list[str]) -> set[str]:
    """Return the set of non-empty _normalize results across the given columns."""
    out: set[str] = set()
    for col in columns:
        if col in df.columns:
            for raw in df[col].dropna().unique():
                norm = _normalize(raw)
                if norm:
                    out.add(norm)
    return out


def _load_anchor_sets(processed_dir: Path) -> dict[str, set[str]]:
    """Build {anchor_type: {normalized_names}} from the materialized anchor sources."""
    anchors: dict[str, set[str]] = {
        "contract": set(),
        "subaward": set(),
        "emma_underwriter": set(),
    }
    for path in (
        processed_dir / "pr_contracts_master.csv",
        processed_dir / "pr_all_awards_master.csv",
    ):
        if path.exists():
            df = pd.read_csv(path, dtype=str, low_memory=False)
            anchors["contract"] |= _normalized_name_set(
                df, ["recipient_name", "vendor_name", "award_recipient_name"]
            )

    sub_path = processed_dir / "pr_subawards_master.csv"
    if sub_path.exists():
        df = pd.read_csv(sub_path, dtype=str, low_memory=False)
        anchors["subaward"] |= _normalized_name_set(
            df, ["sub_recipient_name", "subawardee_name", "recipient_name"]
        )

    for path in (
        processed_dir / "pr_emma_bonds.csv",
        processed_dir / "pr_emma_underwriters.csv",
    ):
        if path.exists():
            df = pd.read_csv(path, dtype=str, low_memory=False)
            anchors["emma_underwriter"] |= _normalized_name_set(
                df, ["issuer", "issuer_name", "underwriter", "underwriter_name", "dealer"]
            )
    return anchors


def _classify_anchor(norm: str, anchors: dict[str, set[str]]) -> tuple[str, str]:
    """Priority: contract > subaward > emma_underwriter > unmatched."""
    if norm in anchors["contract"]:
        return "matched_to_contract", "pr_contracts_master.csv|pr_all_awards_master.csv"
    if norm in anchors["subaward"]:
        return "matched_to_subaward", "pr_subawards_master.csv"
    if norm in anchors["emma_underwriter"]:
        return "matched_to_emma_underwriter", "pr_emma_bonds.csv|pr_emma_underwriters.csv"
    return "unmatched_no_anchor", ""


def build_lobbying_crossref(root: Path | None = None) -> dict:
    """Cross-reference LDA lobbying clients against the awards master.

    Every LDA client surfaces in the output with an ``anchor_status``
    column. Clients whose normalized name matches a federal contract,
    subaward, or EMMA bond party are tagged accordingly; clients with
    no matching anchor are tagged ``unmatched_no_anchor`` so unanchored
    high-value lobbying entities (e.g. Arcadis, Genera PR, Gainwell)
    surface explicitly instead of being silently dropped by an inner
    join.
    """
    root = Path(root) if root is not None else PROJECT_ROOT
    processed_dir = root / "data" / "staging" / "processed"
    logger = setup_logging("analyze_political_crossref.lda")

    awards_path = processed_dir / "pr_all_awards_master.csv"
    lda_path = processed_dir / "pr_lda_filings.csv"
    out_path = processed_dir / "pr_lobbying_crossref.csv"

    if not awards_path.exists():
        logger.error(f"  Awards master not found: {awards_path}")
        return {"rows": 0, "status": "MISSING_AWARDS"}
    if not lda_path.exists():
        logger.error(f"  LDA filings not found: {lda_path}")
        return {"rows": 0, "status": "MISSING_LDA"}

    awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
    lda = pd.read_csv(lda_path, dtype=str, low_memory=False)
    logger.info(f"  {len(awards):,} award rows · {len(lda):,} LDA filing rows")

    award_index = _build_award_index(awards)
    anchors = _load_anchor_sets(processed_dir)

    lda_clients = lda[lda["client_state"] == "PR"].copy() if "client_state" in lda.columns else lda.copy()
    if lda_clients.empty:
        lda_clients = lda.copy()

    lda_clients["_norm"] = lda_clients["client_name"].apply(_normalize)
    lda_clients["_income"] = pd.to_numeric(lda_clients["income"], errors="coerce").fillna(0)
    lda_clients["_expense"] = pd.to_numeric(lda_clients["expenses"], errors="coerce").fillna(0)

    # Capture one evidence filing per client for the unmatched rows.
    evidence_filings = (
        lda_clients[lda_clients["_norm"] != ""]
        .groupby("_norm")["filing_uuid"]
        .first()
        .to_dict()
        if "filing_uuid" in lda_clients.columns
        else {}
    )

    lda_index = (
        lda_clients[lda_clients["_norm"] != ""]
        .groupby("_norm")
        .agg(
            lda_client_name=("client_name", "first"),
            lda_client_description=(
                "client_description" if "client_description" in lda_clients.columns else "client_name",
                "first",
            ),
            filing_count=("filing_uuid", "nunique") if "filing_uuid" in lda_clients.columns else ("client_name", "count"),
            total_registrant_income=("_income", "sum"),
            total_client_expenses=("_expense", "sum"),
            years_active=("filing_year", _year_range) if "filing_year" in lda_clients.columns else ("client_name", "first"),
            issue_codes=("general_issue_codes", lambda x: _merge_pipe(x, 15)) if "general_issue_codes" in lda_clients.columns else ("client_name", "first"),
            lobbyists_hired=("lobbyist_names", lambda x: _merge_pipe(x, 20)) if "lobbyist_names" in lda_clients.columns else ("client_name", "first"),
            registrants_used=("registrant_name", lambda x: "|".join(sorted(x.dropna().unique())[:10])) if "registrant_name" in lda_clients.columns else ("client_name", "first"),
        )
        .reset_index()
    )

    # Left-merge: every LDA client surfaces, with award columns NaN when unanchored.
    merged = lda_index.merge(award_index, on="_norm", how="left")
    merged = merged.rename(columns={"_norm": "normalized_name"})

    # Anchor classification per row.
    statuses = []
    sources = []
    evidence = []
    for _, row in merged.iterrows():
        norm = row["normalized_name"]
        status, src = _classify_anchor(norm, anchors)
        statuses.append(status)
        sources.append(src)
        evidence.append(evidence_filings.get(norm, ""))
    merged["anchor_status"] = statuses
    merged["anchor_source_dataset"] = sources
    merged["anchor_evidence_id"] = evidence

    # Numeric coercions so unmatched rows aren't NaN-typed in the CSV.
    for col in ("total_awards_obligated", "award_count"):
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    sort_col = "total_awards_obligated" if "total_awards_obligated" in merged.columns else "total_registrant_income"
    merged = merged.sort_values(sort_col, ascending=False)

    merged.to_csv(out_path, index=False, encoding="utf-8")

    status_counts = merged["anchor_status"].value_counts().to_dict()
    logger.info(
        f"  Lobbying crossref: {len(merged):,} clients → {out_path.name} | "
        f"anchor breakdown: {status_counts}"
    )
    return {
        "rows": len(merged),
        "status": "OK" if not merged.empty else "EMPTY",
        "path": str(out_path),
        "anchor_breakdown": status_counts,
    }


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------

def build_political_crossref(root: Path | None = None) -> dict:
    """Run both FEC and lobbying crossrefs; return combined summary."""
    fec = build_fec_crossref(root)
    lda = build_lobbying_crossref(root)
    return {"fec": fec, "lda": lda}


def main() -> int:
    parser = argparse.ArgumentParser(description="Political-finance crossref analysis")
    parser.add_argument("--fec", action="store_true", help="Run FEC crossref only")
    parser.add_argument("--lda", action="store_true", help="Run lobbying crossref only")
    args = parser.parse_args()

    run_fec = args.fec or not (args.fec or args.lda)
    run_lda = args.lda or not (args.fec or args.lda)

    if run_fec:
        r = build_fec_crossref()
        print(f"FEC crossref: {r['rows']:,} matched entities → {r.get('path', '')}")
    if run_lda:
        r = build_lobbying_crossref()
        print(f"Lobbying crossref: {r['rows']:,} matched entities → {r.get('path', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
