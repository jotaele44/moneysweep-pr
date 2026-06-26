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
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from moneysweep.runtime.alias_overrides import apply as apply_override
from moneysweep.runtime.alias_overrides import load_overrides
from scripts.config import PROJECT_ROOT, setup_logging


# ---------------------------------------------------------------------------
# Shared name normalisation
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SUFFIXES = {
    "INC",
    "LLC",
    "LLP",
    "CORP",
    "CO",
    "LTD",
    "LP",
    "PC",
    "PLLC",
    "DBA",
    "THE",
    "AND",
    "OF",
    "SA",
    "SL",
    "SRL",
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
            committees_funded=(
                "committee_name",
                lambda x: "|".join(sorted(x.dropna().unique())[:10]),
            ),
            candidates_funded=(
                "candidate_name",
                lambda x: "|".join(sorted(x[x != ""].dropna().unique())[:10]),
            ),
            latest_contribution=("contribution_receipt_date", "max"),
            earliest_contribution=("contribution_receipt_date", "min"),
        )
        .reset_index()
    )

    merged = award_index.merge(fec_index, on="_norm", how="inner")
    if merged.empty:
        logger.warning("  No FEC cross-reference matches found.")
        merged = pd.DataFrame(
            columns=[
                "normalized_name",
                "award_recipient_name",
                "fec_contributor_name",
                "total_awards_obligated",
                "total_contributions",
                "award_count",
                "contribution_count",
                "award_datasets",
                "award_years",
                "committees_funded",
                "candidates_funded",
                "latest_contribution",
                "earliest_contribution",
            ]
        )
    else:
        merged = merged.rename(columns={"_norm": "normalized_name"})
        merged = merged.sort_values("total_awards_obligated", ascending=False)

    merged.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  FEC crossref: {len(merged):,} matched entities → {out_path.name}")
    return {
        "rows": len(merged),
        "status": "OK" if not merged.empty else "EMPTY",
        "path": str(out_path),
    }


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

    lda_clients = (
        lda[lda["client_state"] == "PR"].copy() if "client_state" in lda.columns else lda.copy()
    )
    if lda_clients.empty:
        lda_clients = lda.copy()

    lda_clients["_norm"] = lda_clients["client_name"].apply(_normalize)
    lda_clients["_income"] = pd.to_numeric(lda_clients["income"], errors="coerce").fillna(0)
    lda_clients["_expense"] = pd.to_numeric(lda_clients["expenses"], errors="coerce").fillna(0)

    # Capture one evidence filing per client for the unmatched rows.
    evidence_filings = (
        lda_clients[lda_clients["_norm"] != ""].groupby("_norm")["filing_uuid"].first().to_dict()
        if "filing_uuid" in lda_clients.columns
        else {}
    )

    lda_index = (
        lda_clients[lda_clients["_norm"] != ""]
        .groupby("_norm")
        .agg(
            lda_client_name=("client_name", "first"),
            lda_client_description=(
                "client_description"
                if "client_description" in lda_clients.columns
                else "client_name",
                "first",
            ),
            filing_count=("filing_uuid", "nunique")
            if "filing_uuid" in lda_clients.columns
            else ("client_name", "count"),
            total_registrant_income=("_income", "sum"),
            total_client_expenses=("_expense", "sum"),
            years_active=("filing_year", _year_range)
            if "filing_year" in lda_clients.columns
            else ("client_name", "first"),
            issue_codes=("general_issue_codes", lambda x: _merge_pipe(x, 15))
            if "general_issue_codes" in lda_clients.columns
            else ("client_name", "first"),
            lobbyists_hired=("lobbyist_names", lambda x: _merge_pipe(x, 20))
            if "lobbyist_names" in lda_clients.columns
            else ("client_name", "first"),
            registrants_used=(
                "registrant_name",
                lambda x: "|".join(sorted(x.dropna().unique())[:10]),
            )
            if "registrant_name" in lda_clients.columns
            else ("client_name", "first"),
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

    sort_col = (
        "total_awards_obligated"
        if "total_awards_obligated" in merged.columns
        else "total_registrant_income"
    )
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
# Cabildero / registrant crossref
# ---------------------------------------------------------------------------

CABILDERO_CROSSREF_COLUMNS = [
    "normalized_name",
    "registrant_name",
    "source",
    "lda_filing_count",
    "lda_total_income",
    "lda_clients_represented",
    "lda_issue_codes",
    "lda_years_active",
    "pr_clients_represented",
    "pr_registration_years",
    "anchor_status",
    "anchor_source_dataset",
    "award_recipient_name",
    "total_awards_obligated",
    "award_count",
    "award_datasets",
    "award_years",
]


def _blank_cabildero_record(norm: str) -> dict:
    rec: dict = {col: "" for col in CABILDERO_CROSSREF_COLUMNS}
    rec["normalized_name"] = norm
    rec["lda_filing_count"] = 0
    rec["lda_total_income"] = 0.0
    rec["total_awards_obligated"] = 0
    rec["award_count"] = 0
    rec["_in_lda"] = False
    rec["_in_pr"] = False
    return rec


def build_cabildero_crossref(root: Path | None = None) -> dict:
    """Cross-reference lobbying *registrants* against the awards master.

    ``build_lobbying_crossref`` handles LDA *clients* (entities that hire
    lobbyists); this handles the lobbyists/registrants themselves — federal LDA
    registrant firms and PR OEG state-level cabilderos. It unifies the federal and
    PR-state lobbying universes (tagging ``source`` as ``federal_lda``, ``pr_oeg``,
    or ``both``) and tags each registrant with an ``anchor_status`` so lobbyists
    that *also* receive federal awards (dual-influence) surface explicitly.
    """
    root = Path(root) if root is not None else PROJECT_ROOT
    processed_dir = root / "data" / "staging" / "processed"
    logger = setup_logging("analyze_political_crossref.cabildero")

    lda_path = processed_dir / "pr_lda_filings.csv"
    cab_path = processed_dir / "pr_cabilderos.csv"
    awards_path = processed_dir / "pr_all_awards_master.csv"
    out_path = processed_dir / "pr_cabildero_crossref.csv"

    if not lda_path.exists() and not cab_path.exists():
        logger.error("  Neither pr_lda_filings.csv nor pr_cabilderos.csv present")
        return {"rows": 0, "status": "MISSING_LOBBYING_SOURCES"}

    records: dict[str, dict] = {}

    # Federal LDA registrants.
    if lda_path.exists():
        lda = pd.read_csv(lda_path, dtype=str, low_memory=False)
        if "registrant_name" in lda.columns:
            lda["_norm"] = lda["registrant_name"].apply(_normalize)
            for norm, grp in lda[lda["_norm"] != ""].groupby("_norm"):
                rec = records.setdefault(norm, _blank_cabildero_record(norm))
                rec["registrant_name"] = grp["registrant_name"].iloc[0]
                rec["_in_lda"] = True
                rec["lda_filing_count"] = (
                    int(grp["filing_uuid"].nunique())
                    if "filing_uuid" in grp.columns
                    else int(len(grp))
                )
                if "income" in grp.columns:
                    rec["lda_total_income"] = float(
                        pd.to_numeric(grp["income"], errors="coerce").fillna(0).sum()
                    )
                if "client_name" in grp.columns:
                    rec["lda_clients_represented"] = _merge_pipe(grp["client_name"], 25)
                if "general_issue_codes" in grp.columns:
                    rec["lda_issue_codes"] = _merge_pipe(grp["general_issue_codes"], 15)
                if "filing_year" in grp.columns:
                    rec["lda_years_active"] = _year_range(grp["filing_year"])

    # PR OEG state-level cabilderos.
    if cab_path.exists():
        cab = pd.read_csv(cab_path, dtype=str, low_memory=False)
        if "lobbyist_name" in cab.columns:
            cab["_norm"] = cab["lobbyist_name"].apply(_normalize)
            for norm, grp in cab[cab["_norm"] != ""].groupby("_norm"):
                rec = records.setdefault(norm, _blank_cabildero_record(norm))
                rec["_in_pr"] = True
                if not rec["registrant_name"]:
                    rec["registrant_name"] = grp["lobbyist_name"].iloc[0]
                if "client_name" in grp.columns:
                    rec["pr_clients_represented"] = _merge_pipe(grp["client_name"], 25)
                if "registration_year" in grp.columns:
                    rec["pr_registration_years"] = _year_range(grp["registration_year"])

    if not records:
        pd.DataFrame(columns=CABILDERO_CROSSREF_COLUMNS).to_csv(out_path, index=False)
        logger.info("  Cabildero crossref: 0 registrants")
        return {"rows": 0, "status": "EMPTY", "path": str(out_path)}

    anchors = _load_anchor_sets(processed_dir)
    award_lookup: dict[str, dict] = {}
    if awards_path.exists():
        awards = pd.read_csv(awards_path, dtype=str, low_memory=False)
        if "recipient_name" in awards.columns:
            award_lookup = _build_award_index(awards).set_index("_norm").to_dict("index")

    rows = []
    for norm, rec in records.items():
        rec["source"] = (
            "both"
            if rec["_in_lda"] and rec["_in_pr"]
            else "federal_lda"
            if rec["_in_lda"]
            else "pr_oeg"
        )
        status, src = _classify_anchor(norm, anchors)
        rec["anchor_status"] = status
        rec["anchor_source_dataset"] = src
        aw = award_lookup.get(norm, {})
        rec["award_recipient_name"] = aw.get("award_recipient_name", "")
        rec["total_awards_obligated"] = aw.get("total_awards_obligated", 0)
        rec["award_count"] = aw.get("award_count", 0)
        rec["award_datasets"] = aw.get("award_datasets", "")
        rec["award_years"] = aw.get("award_years", "")
        rows.append({col: rec[col] for col in CABILDERO_CROSSREF_COLUMNS})

    df = pd.DataFrame(rows, columns=CABILDERO_CROSSREF_COLUMNS)
    df["total_awards_obligated"] = pd.to_numeric(
        df["total_awards_obligated"], errors="coerce"
    ).fillna(0)
    df = df.sort_values(["total_awards_obligated", "lda_filing_count"], ascending=False)
    df.to_csv(out_path, index=False, encoding="utf-8")

    dual = int((df["anchor_status"] != "unmatched_no_anchor").sum())
    source_counts = df["source"].value_counts().to_dict()
    logger.info(
        f"  Cabildero crossref: {len(df):,} registrants → {out_path.name} | "
        f"sources: {source_counts} | dual-influence (anchored): {dual}"
    )
    return {
        "rows": len(df),
        "status": "OK",
        "path": str(out_path),
        "sources": source_counts,
        "dual_influence": dual,
    }


# ---------------------------------------------------------------------------
# NGO ↔ political-donation crossref
# ---------------------------------------------------------------------------

NGO_DONATION_CROSSREF_COLUMNS = [
    "ngo_id",
    "normalized_name",
    "legal_name",
    "ein",
    "municipality",
    "irs_subsection",
    "entity_type",
    "confidence",
    "review_status",
    "politically_active_subsection",
    "donation_sources",
    "fec_total_contributions",
    "fec_contribution_count",
    "fec_committees_funded",
    "fec_candidates_funded",
    "fec_earliest",
    "fec_latest",
    "pr_total_contributions",
    "pr_contribution_count",
    "pr_recipients",
    "pr_parties",
    "pr_earliest",
    "pr_latest",
    "total_political_contributions",
    "matched_alias",
]

_POLITICAL_SUBSECTIONS = {"4", "5", "6"}
_RESTRICTED_SUBSECTION = "3"


def _classify_subsection(raw: object) -> str:
    """Map IRS 501(c) subsection to a political-activity bucket.

    501(c)(4)/(5)/(6) are the subsections most likely to engage in political
    activity (social welfare, labor, business leagues). 501(c)(3) is restricted
    from political campaign intervention. Everything else is bucketed ``other``.
    """
    digits = re.sub(r"\D+", "", str(raw or ""))
    if digits in _POLITICAL_SUBSECTIONS:
        return "likely_political"
    if digits == _RESTRICTED_SUBSECTION:
        return "restricted_charity"
    return "other"


def _ngo_name_variants(row: pd.Series) -> list[str]:
    """Return normalized name + alias variants for matching against donors."""
    variants: list[str] = []
    seen: set[str] = set()
    legal = _normalize(row.get("legal_name"))
    if legal:
        variants.append(legal)
        seen.add(legal)
    raw_aliases = row.get("aliases", "")
    if raw_aliases and not pd.isna(raw_aliases):
        text = str(raw_aliases).strip()
        candidates: list[str] = []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    candidates = [str(x) for x in parsed]
            except (json.JSONDecodeError, ValueError):
                candidates = [text]
        elif "|" in text:
            candidates = text.split("|")
        else:
            candidates = [text]
        for cand in candidates:
            norm = _normalize(cand)
            if norm and norm not in seen:
                variants.append(norm)
                seen.add(norm)
    return variants


def _build_fec_org_index(fec: pd.DataFrame) -> pd.DataFrame:
    """FEC contributions grouped by normalized contributor name, organizations only."""
    df = fec.copy()
    # Exclude individual contributors so we don't match on personal names that
    # happen to collide with an NGO. is_individual is written by download_fec
    # from entity_type=="IND"; tolerate both raw FEC and our downstream rows.
    if "is_individual" in df.columns:
        df = df[df["is_individual"].astype(str).str.lower() != "true"]
    if "entity_type" in df.columns:
        df = df[df["entity_type"].astype(str).str.upper() != "IND"]
    if df.empty:
        return pd.DataFrame(columns=["_norm"])
    df["_norm"] = df["contributor_name"].apply(_normalize)
    df["_amt"] = pd.to_numeric(df.get("contribution_receipt_amount"), errors="coerce").fillna(0)
    return (
        df[df["_norm"] != ""]
        .groupby("_norm")
        .agg(
            fec_total_contributions=("_amt", "sum"),
            fec_contribution_count=("_amt", "count"),
            fec_committees_funded=(
                "committee_name",
                lambda x: "|".join(sorted({c for c in x.dropna() if c})[:10]),
            ),
            fec_candidates_funded=(
                "candidate_name",
                lambda x: "|".join(sorted({c for c in x.dropna() if c})[:10]),
            ),
            fec_earliest=("contribution_receipt_date", "min"),
            fec_latest=("contribution_receipt_date", "max"),
        )
        .reset_index()
    )


def _build_pr_donation_index(donations: pd.DataFrame) -> pd.DataFrame:
    """PR (CEE / OCE) donations grouped by normalized donor name."""
    df = donations.copy()
    df["_norm"] = df["donor_name"].apply(_normalize)
    df["_amt"] = pd.to_numeric(df.get("amount"), errors="coerce").fillna(0)
    return (
        df[df["_norm"] != ""]
        .groupby("_norm")
        .agg(
            pr_total_contributions=("_amt", "sum"),
            pr_contribution_count=("_amt", "count"),
            pr_recipients=(
                "candidate_or_committee",
                lambda x: "|".join(sorted({c for c in x.dropna() if c})[:10]),
            )
            if "candidate_or_committee" in df.columns
            else ("donor_name", "count"),
            pr_parties=("party", lambda x: "|".join(sorted({c for c in x.dropna() if c})[:10]))
            if "party" in df.columns
            else ("donor_name", "count"),
            pr_earliest=("contribution_date", "min")
            if "contribution_date" in df.columns
            else ("donor_name", "count"),
            pr_latest=("contribution_date", "max")
            if "contribution_date" in df.columns
            else ("donor_name", "count"),
        )
        .reset_index()
    )


def _load_pr_donations(processed_dir: Path) -> pd.DataFrame:
    """Concatenate CEE (donaciones) + OCE (Contralor Electoral) donations if present."""
    frames: list[pd.DataFrame] = []
    for fname in ("pr_donaciones.csv", "pr_oce_donations.csv"):
        path = processed_dir / fname
        if path.exists():
            df = pd.read_csv(path, dtype=str, low_memory=False)
            if not df.empty and "donor_name" in df.columns:
                df["_origin_file"] = fname
                frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["donor_name"])
    return pd.concat(frames, ignore_index=True, sort=False)


def build_ngo_donation_crossref(root: Path | None = None) -> dict:
    """Cross-reference NGOs against political-donation feeds (federal FEC + PR CEE/OCE).

    Identifies organizations in ``ngos_master.csv`` that appear as **donors** to
    political campaigns / committees. Matches on the normalized NGO ``legal_name``
    and any alias in the ``aliases`` column. FEC individuals are excluded to
    avoid personal-name collisions. The output is NGO-centric (one row per
    matched NGO) with separate federal / PR totals and a derived
    ``politically_active_subsection`` flag derived from ``irs_subsection``
    (501(c)(4)/(5)/(6) → ``likely_political``, (c)(3) → ``restricted_charity``).
    """
    root = Path(root) if root is not None else PROJECT_ROOT
    processed_dir = root / "data" / "staging" / "processed"
    ngo_dir = processed_dir / "ngos"
    logger = setup_logging("analyze_political_crossref.ngo")

    ngos_path = ngo_dir / "ngos_master.csv"
    fec_path = processed_dir / "pr_fec_contributions.csv"
    out_path = ngo_dir / "ngo_political_donations.csv"
    ngo_dir.mkdir(parents=True, exist_ok=True)

    if not ngos_path.exists():
        logger.error(f"  NGO master not found: {ngos_path}")
        return {"rows": 0, "status": "MISSING_NGO_MASTER"}

    ngos = pd.read_csv(ngos_path, dtype=str, low_memory=False)
    if ngos.empty:
        pd.DataFrame(columns=NGO_DONATION_CROSSREF_COLUMNS).to_csv(out_path, index=False)
        return {"rows": 0, "status": "EMPTY_NGO_MASTER", "path": str(out_path)}

    fec_df = (
        pd.read_csv(fec_path, dtype=str, low_memory=False) if fec_path.exists() else pd.DataFrame()
    )
    pr_df = _load_pr_donations(processed_dir)

    if (fec_df.empty or "contributor_name" not in fec_df.columns) and pr_df.empty:
        logger.error("  No donation feeds present (FEC and PR CEE/OCE both absent or empty)")
        pd.DataFrame(columns=NGO_DONATION_CROSSREF_COLUMNS).to_csv(out_path, index=False)
        return {"rows": 0, "status": "MISSING_DONATIONS", "path": str(out_path)}

    logger.info(
        f"  {len(ngos):,} NGOs · {len(fec_df):,} FEC rows · {len(pr_df):,} PR donation rows"
    )

    fec_index = (
        _build_fec_org_index(fec_df)
        if not fec_df.empty and "contributor_name" in fec_df.columns
        else pd.DataFrame(columns=["_norm"])
    )
    pr_index = (
        _build_pr_donation_index(pr_df) if not pr_df.empty else pd.DataFrame(columns=["_norm"])
    )

    fec_lookup = fec_index.set_index("_norm").to_dict("index") if not fec_index.empty else {}
    pr_lookup = pr_index.set_index("_norm").to_dict("index") if not pr_index.empty else {}

    rows: list[dict] = []
    for _, ngo in ngos.iterrows():
        variants = _ngo_name_variants(ngo)
        if not variants:
            continue
        matched_alias = ""
        fec_match: dict | None = None
        pr_match: dict | None = None
        for v in variants:
            if fec_match is None and v in fec_lookup:
                fec_match = fec_lookup[v]
                matched_alias = matched_alias or v
            if pr_match is None and v in pr_lookup:
                pr_match = pr_lookup[v]
                matched_alias = matched_alias or v
            if fec_match is not None and pr_match is not None:
                break
        if fec_match is None and pr_match is None:
            continue

        donation_sources = (
            "both" if (fec_match and pr_match) else ("federal_fec" if fec_match else "pr")
        )
        fec_total = float((fec_match or {}).get("fec_total_contributions", 0) or 0)
        pr_total = float((pr_match or {}).get("pr_total_contributions", 0) or 0)
        rec: dict = {col: "" for col in NGO_DONATION_CROSSREF_COLUMNS}
        rec.update(
            {
                "ngo_id": ngo.get("ngo_id", ""),
                "normalized_name": variants[0],
                "legal_name": ngo.get("legal_name", ""),
                "ein": ngo.get("ein", ""),
                "municipality": ngo.get("municipality", ""),
                "irs_subsection": ngo.get("irs_subsection", ""),
                "entity_type": ngo.get("entity_type", ""),
                "confidence": ngo.get("confidence", ""),
                "review_status": ngo.get("review_status", ""),
                "politically_active_subsection": _classify_subsection(
                    ngo.get("irs_subsection", "")
                ),
                "donation_sources": donation_sources,
                "matched_alias": matched_alias,
                "total_political_contributions": fec_total + pr_total,
            }
        )
        if fec_match:
            rec["fec_total_contributions"] = fec_total
            rec["fec_contribution_count"] = int(fec_match.get("fec_contribution_count", 0) or 0)
            rec["fec_committees_funded"] = fec_match.get("fec_committees_funded", "")
            rec["fec_candidates_funded"] = fec_match.get("fec_candidates_funded", "")
            rec["fec_earliest"] = fec_match.get("fec_earliest", "")
            rec["fec_latest"] = fec_match.get("fec_latest", "")
        if pr_match:
            rec["pr_total_contributions"] = pr_total
            rec["pr_contribution_count"] = int(pr_match.get("pr_contribution_count", 0) or 0)
            rec["pr_recipients"] = pr_match.get("pr_recipients", "")
            rec["pr_parties"] = pr_match.get("pr_parties", "")
            rec["pr_earliest"] = pr_match.get("pr_earliest", "")
            rec["pr_latest"] = pr_match.get("pr_latest", "")
        rows.append(rec)

    if not rows:
        pd.DataFrame(columns=NGO_DONATION_CROSSREF_COLUMNS).to_csv(out_path, index=False)
        logger.info(f"  NGO donation crossref: 0 matched NGOs → {out_path.name}")
        return {"rows": 0, "status": "EMPTY", "path": str(out_path)}

    df = pd.DataFrame(rows, columns=NGO_DONATION_CROSSREF_COLUMNS)
    df["total_political_contributions"] = pd.to_numeric(
        df["total_political_contributions"], errors="coerce"
    ).fillna(0)
    df = df.sort_values("total_political_contributions", ascending=False)
    df.to_csv(out_path, index=False, encoding="utf-8")

    sources_breakdown = df["donation_sources"].value_counts().to_dict()
    subsection_breakdown = df["politically_active_subsection"].value_counts().to_dict()
    logger.info(
        f"  NGO donation crossref: {len(df):,} matched NGOs → {out_path.name} | "
        f"sources: {sources_breakdown} | subsection flags: {subsection_breakdown}"
    )
    return {
        "rows": len(df),
        "status": "OK",
        "path": str(out_path),
        "donation_sources": sources_breakdown,
        "politically_active_subsection": subsection_breakdown,
    }


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


def build_political_crossref(root: Path | None = None) -> dict:
    """Run FEC, lobbying, cabildero, and NGO-donation crossrefs."""
    fec = build_fec_crossref(root)
    lda = build_lobbying_crossref(root)
    cabildero = build_cabildero_crossref(root)
    ngo = build_ngo_donation_crossref(root)
    return {"fec": fec, "lda": lda, "cabildero": cabildero, "ngo": ngo}


def main() -> int:
    parser = argparse.ArgumentParser(description="Political-finance crossref analysis")
    parser.add_argument("--fec", action="store_true", help="Run FEC crossref only")
    parser.add_argument("--lda", action="store_true", help="Run lobbying (client) crossref only")
    parser.add_argument(
        "--cabildero", action="store_true", help="Run cabildero/registrant crossref only"
    )
    parser.add_argument(
        "--ngo", action="store_true", help="Run NGO ↔ political donation crossref only"
    )
    args = parser.parse_args()

    selected = args.fec or args.lda or args.cabildero or args.ngo
    run_fec = args.fec or not selected
    run_lda = args.lda or not selected
    run_cab = args.cabildero or not selected
    run_ngo = args.ngo or not selected

    if run_fec:
        r = build_fec_crossref()
        print(f"FEC crossref: {r['rows']:,} matched entities → {r.get('path', '')}")
    if run_lda:
        r = build_lobbying_crossref()
        print(f"Lobbying crossref: {r['rows']:,} matched entities → {r.get('path', '')}")
    if run_cab:
        r = build_cabildero_crossref()
        print(f"Cabildero crossref: {r['rows']:,} registrants → {r.get('path', '')}")
    if run_ngo:
        r = build_ngo_donation_crossref()
        print(f"NGO donation crossref: {r['rows']:,} matched NGOs → {r.get('path', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
