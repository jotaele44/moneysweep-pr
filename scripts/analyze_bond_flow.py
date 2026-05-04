"""
Cross-reference PR municipal bond market participants (issuers, underwriters,
dealers) against the federal award entity master to identify dual-role actors.

Key question: Which entities received federal contracts/grants AND earned
underwriting fees or dealer spreads from Puerto Rico municipal bonds? These
"dual-role" entities extracted value from both the federal spending side and
the capital markets side of Puerto Rico's financial ecosystem.

Inputs:
  data/staging/processed/pr_emma_bonds.csv         — CUSIP-level bond data
  data/staging/processed/pr_emma_underwriters.csv  — underwriter aggregates
  data/staging/processed/pr_msrb_trades.csv        — secondary market trades
  data/staging/processed/entity_master.csv         — federal award recipients

Output:
  data/staging/processed/pr_bond_flow.csv

Usage:
  python3 scripts/analyze_bond_flow.py
  python3 scripts/analyze_bond_flow.py --force
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name
from scripts.sam_enrichment import name_similarity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MATCH_THRESHOLD = 0.75   # name similarity threshold for entity matching
UW_SPREAD_EST   = 0.005  # estimated underwriter gross spread (0.5% of par)

BOND_FLOW_COLUMNS = [
    "entity_key", "canonical_name",
    # Issuer side
    "bond_issuer_flag", "bonds_issued_count", "bonds_issued_par",
    # Underwriter side
    "bond_underwriter_flag", "bonds_underwritten_count",
    "bonds_underwritten_par", "estimated_underwriter_fee",
    # Dealer side
    "bond_dealer_flag", "dealer_volume_par",
    # Cross-role flags
    "is_dual_role",           # federal award recipient AND underwriter/dealer
    "is_issuer_and_awardee",  # bond issuer AND federal award recipient
    "dual_role_awards",       # total federal awards for dual-role entities
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: Path, label: str, logger) -> pd.DataFrame:
    if not path.exists():
        logger.info(f"  {label}: not found — {path.name}")
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, low_memory=False)
    logger.info(f"  {label}: {len(df):,} rows")
    return df


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _best_match(name_norm: str, candidates: pd.Series) -> float:
    """Return the best similarity score for name_norm against any candidate."""
    if not name_norm or candidates.empty:
        return 0.0
    scores = candidates.apply(lambda c: name_similarity(name_norm, str(c)))
    return float(scores.max()) if not scores.empty else 0.0


def _match_to_entity(name_norm: str, entity_norms: pd.Series) -> bool:
    """True if name_norm matches any entity in entity_master at threshold."""
    return _best_match(name_norm, entity_norms) >= MATCH_THRESHOLD


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    proc = root / "data" / "staging" / "processed"
    out_path = proc / "pr_bond_flow.csv"
    proc.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("analyze_bond_flow", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  Bond flow: exists ({rows:,} rows) — skipping (use --force).")
        return {"status": "CACHED", "rows": rows}

    # Load inputs
    bonds_df  = _load(proc / "pr_emma_bonds.csv",        "EMMA bonds",       logger)
    uw_df     = _load(proc / "pr_emma_underwriters.csv",  "EMMA underwriters", logger)
    trades_df = _load(proc / "pr_msrb_trades.csv",        "MSRB trades",      logger)
    entity_df = _load(proc / "entity_master.csv",         "entity_master",    logger)

    if entity_df.empty:
        logger.warning("  entity_master.csv missing — run build_unified_master.py first")
        pd.DataFrame(columns=BOND_FLOW_COLUMNS).to_csv(out_path, index=False)
        return {"status": "SKIPPED", "reason": "no_entity_master", "rows": 0}

    # Normalize entity master names for matching
    norm_col = next(
        (c for c in ["canonical_name", "recipient_name_normalized"] if c in entity_df.columns),
        None,
    )
    if norm_col:
        entity_df["_norm"] = entity_df[norm_col].fillna("").apply(_normalize_name)
    else:
        entity_df["_norm"] = ""

    entity_norms = entity_df["_norm"]
    entity_awards = {}
    for _, row in entity_df.iterrows():
        norm = str(row.get("_norm") or "")
        if norm:
            entity_awards[norm] = _safe_float(row.get("total_obligated") or
                                               row.get("total_obligation") or 0)

    # ------------------------------------------------------------------
    # Build bond-side entity sets
    # ------------------------------------------------------------------

    # --- Issuers from bonds ---
    issuer_stats: dict[str, dict] = {}
    if not bonds_df.empty and "issuer_normalized" in bonds_df.columns:
        bonds_df["_par"] = pd.to_numeric(bonds_df.get("par_amount"), errors="coerce").fillna(0)
        for iss_norm, grp in bonds_df.groupby("issuer_normalized"):
            if not iss_norm:
                continue
            issuer_stats[iss_norm] = {
                "name":       str(grp["issuer_name"].iloc[0]) if "issuer_name" in grp.columns else iss_norm,
                "count":      len(grp),
                "par":        float(grp["_par"].sum()),
            }

    # --- Underwriters from underwriter aggregates (preferred) ---
    uw_stats: dict[str, dict] = {}
    if not uw_df.empty and "underwriter_normalized" in uw_df.columns:
        for _, row in uw_df.iterrows():
            uw_norm = str(row.get("underwriter_normalized") or "")
            if not uw_norm:
                continue
            uw_stats[uw_norm] = {
                "name":   str(row.get("underwriter_name") or uw_norm),
                "count":  int(_safe_float(row.get("deal_count") or 0)),
                "par":    _safe_float(row.get("total_par_amount") or 0),
            }
    elif not bonds_df.empty and "underwriter_normalized" in bonds_df.columns:
        # Fall back to aggregation from bond rows
        valid = bonds_df[bonds_df["underwriter_normalized"].notna() &
                         (bonds_df["underwriter_normalized"] != "")]
        bonds_df["_par"] = pd.to_numeric(bonds_df.get("par_amount"), errors="coerce").fillna(0)
        for uw_norm, grp in valid.groupby("underwriter_normalized"):
            uw_stats[uw_norm] = {
                "name":   str(grp["underwriter_name"].iloc[0]) if "underwriter_name" in grp.columns else uw_norm,
                "count":  int(grp["cusip"].nunique()) if "cusip" in grp.columns else len(grp),
                "par":    float(grp["_par"].sum()),
            }

    # --- Dealers from trade data ---
    dealer_stats: dict[str, dict] = {}
    if not trades_df.empty and "dealer_normalized" in trades_df.columns:
        trades_df["_par"] = pd.to_numeric(trades_df.get("par_traded"), errors="coerce").fillna(0)
        for dl_norm, grp in trades_df.groupby("dealer_normalized"):
            if not dl_norm:
                continue
            dealer_stats[dl_norm] = {
                "name": str(grp["dealer_name"].iloc[0]) if "dealer_name" in grp.columns else dl_norm,
                "par":  float(grp["_par"].sum()),
            }

    logger.info(
        f"  Bond entities — issuers: {len(issuer_stats):,}, "
        f"underwriters: {len(uw_stats):,}, dealers: {len(dealer_stats):,}"
    )

    # ------------------------------------------------------------------
    # Build output: one row per entity_master entry, augmented with bond data
    # ------------------------------------------------------------------
    rows = []
    dual_role_count = 0
    issuer_awardee_count = 0

    for _, ent in entity_df.iterrows():
        entity_key  = str(ent.get("entity_key") or ent.get("canonical_name") or "")
        canonical   = str(ent.get("canonical_name") or entity_key)
        ent_norm    = str(ent.get("_norm") or "")
        awards_val  = entity_awards.get(ent_norm, 0.0)

        # Match entity against issuer / underwriter / dealer norms
        def _match_dict(stats_dict: dict) -> tuple[bool, dict | None]:
            best_score = 0.0
            best_key   = None
            for bond_norm in stats_dict:
                sc = name_similarity(ent_norm, bond_norm)
                if sc > best_score:
                    best_score = sc
                    best_key   = bond_norm
            if best_score >= MATCH_THRESHOLD and best_key:
                return True, stats_dict[best_key]
            return False, None

        is_issuer,      iss_data = _match_dict(issuer_stats)
        is_underwriter, uw_data  = _match_dict(uw_stats)
        is_dealer,      dl_data  = _match_dict(dealer_stats)

        bonds_issued_count   = iss_data["count"] if iss_data else 0
        bonds_issued_par     = iss_data["par"]   if iss_data else 0.0
        uw_count             = uw_data["count"]  if uw_data  else 0
        uw_par               = uw_data["par"]    if uw_data  else 0.0
        estimated_uw_fee     = round(uw_par * UW_SPREAD_EST, 2)
        dealer_vol           = dl_data["par"]    if dl_data  else 0.0

        is_dual_role          = int((is_underwriter or is_dealer) and awards_val > 0)
        is_issuer_and_awardee = int(is_issuer and awards_val > 0)

        if is_dual_role:
            dual_role_count += 1
        if is_issuer_and_awardee:
            issuer_awardee_count += 1

        rows.append({
            "entity_key":              entity_key,
            "canonical_name":          canonical,
            "bond_issuer_flag":        int(is_issuer),
            "bonds_issued_count":      bonds_issued_count,
            "bonds_issued_par":        bonds_issued_par,
            "bond_underwriter_flag":   int(is_underwriter),
            "bonds_underwritten_count": uw_count,
            "bonds_underwritten_par":  uw_par,
            "estimated_underwriter_fee": estimated_uw_fee,
            "bond_dealer_flag":        int(is_dealer),
            "dealer_volume_par":       dealer_vol,
            "is_dual_role":            is_dual_role,
            "is_issuer_and_awardee":   is_issuer_and_awardee,
            "dual_role_awards":        awards_val if is_dual_role else 0.0,
        })

    df_out = pd.DataFrame(rows, columns=BOND_FLOW_COLUMNS)
    df_out = df_out.sort_values(["is_dual_role", "bonds_underwritten_par"], ascending=False)
    df_out.to_csv(out_path, index=False)

    n = len(df_out)
    logger.info(
        f"  Bond flow: {n:,} entities, {dual_role_count:,} dual-role "
        f"(contractor + bond market), {issuer_awardee_count:,} issuer+awardee "
        f"→ {out_path.name}"
    )

    if dual_role_count > 0:
        dual = df_out[df_out["is_dual_role"] == 1].head(10)
        logger.info("  Top dual-role entities (federal awards + bond market):")
        for _, row in dual.iterrows():
            logger.info(
                f"    {str(row['canonical_name'])[:50]:<50}  "
                f"awards: ${_safe_float(row['dual_role_awards']):>14,.0f}  "
                f"uw_par: ${_safe_float(row['bonds_underwritten_par']):>14,.0f}"
            )

    return {
        "status":                "OK",
        "rows":                  n,
        "dual_role_count":       dual_role_count,
        "issuer_awardee_count":  issuer_awardee_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-reference PR bond market participants with federal award entities"
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    return 0 if result.get("status") in ("OK", "CACHED", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
