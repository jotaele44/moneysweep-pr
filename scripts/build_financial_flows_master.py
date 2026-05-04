"""
Build financial_flows_master — synthesizes all upstream financial data into a single
canonical financial-flow table covering the full federal→PR execution chain.

Architecture:
  [FEMA PA v2]  [HUD DRGR]  [USASpending/FPDS]  [PR Procurement]
        ↓             ↓              ↓                  ↓
              financial_flows_master.parquet

Inputs (all optional — graceful if missing):
  data/normalized/fema_pa_projects_v2.parquet
  data/normalized/fema_pa_portal_178_pws.parquet
  data/linked/fema_178_pw_linkage.csv
  data/normalized/hud_drgr_grants.parquet
  data/normalized/hud_drgr_activities.parquet
  data/normalized/hud_drgr_drawdowns.parquet
  data/normalized/hud_drgr_projects.parquet
  data/staging/processed/pr_cor3_projects.csv
  data/staging/processed/pr_prasa_contracts.csv
  data/staging/processed/pr_compras_awards.csv
  data/staging/processed/pr_contracts_master.csv  (or pr_all_awards_master.csv)

Output:
  data/normalized/financial_flows_master.parquet

Usage:
  python3 scripts/build_financial_flows_master.py
  python3 scripts/build_financial_flows_master.py --force
"""

import argparse
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.build_unified_master import _normalize_name
from scripts.config import PROJECT_ROOT, setup_logging

NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"

FLOW_COLUMNS = [
    "flow_id", "flow_type", "source_system", "source_file",
    "funding_source", "appropriation", "grant_number", "disaster_number",
    "pw_number", "activity_id", "project_id",
    "applicant_or_grantee", "responsible_organization", "prime_vendor", "sub_vendor",
    "amount_type", "amount", "obligation_date", "drawdown_date", "award_date",
    "municipality", "asset_id", "contract_id", "parent_uei",
    "link_confidence", "evidence_path",
]

TODAY = str(date.today())


def _fid():
    return str(uuid.uuid4())[:12]


def _load_parquet(path, logger):
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path, engine="pyarrow")
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _load_csv(path, logger):
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
        logger.info(f"  Loaded {len(df):,} rows from {path.name}")
        return df
    except Exception as e:
        logger.warning(f"  Failed to read {path.name}: {e}")
        return pd.DataFrame()


def _row(**kwargs):
    base = {col: "" for col in FLOW_COLUMNS}
    base.update(kwargs)
    return base


def _ingest_fema_pa(df_v2, df_portal, df_linkage, logger):
    rows = []
    if df_v2.empty:
        return rows

    linkage_lookup = {}
    if not df_linkage.empty and "pw_number" in df_linkage.columns:
        for _, r in df_linkage.iterrows():
            pw = str(r.get("pw_number", "")).strip()
            dis = str(r.get("disaster_number", "")).strip()
            if pw:
                linkage_lookup[(pw, dis)] = r

    for _, r in df_v2.iterrows():
        pw  = str(r.get("pw_number", "")).strip()
        dis = str(r.get("disaster_number", "")).strip()
        link = linkage_lookup.get((pw, dis), {})

        rows.append(_row(
            flow_id            = _fid(),
            flow_type          = "federal_disaster_grant",
            source_system      = "openfema_v2",
            source_file        = "fema_pa_projects_v2.parquet",
            funding_source     = "FEMA_PA",
            disaster_number    = dis,
            pw_number          = pw,
            applicant_or_grantee = str(r.get("applicant_name", "")).strip(),
            responsible_organization = str(r.get("applicant_name", "")).strip(),
            prime_vendor       = str(link.get("recipient_name", "")) if link else "",
            amount_type        = "federal_share_obligated",
            amount             = str(r.get("federal_share_obligated", "")),
            obligation_date    = str(r.get("obligation_date", r.get("pw_date", ""))),
            municipality       = str(r.get("county", "")),
            contract_id        = str(link.get("contract_id", "")) if link else "",
            link_confidence    = str(link.get("link_confidence", "none")) if link else "none",
            evidence_path      = "fema_pa_projects_v2.parquet",
        ))

    logger.info(f"  FEMA PA: {len(rows):,} flow rows")
    return rows


def _ingest_hud_drgr(df_projects, df_activities, df_drawdowns, logger):
    rows = []

    # Grant-level flows from projects
    if not df_projects.empty:
        for _, r in df_projects.iterrows():
            gn = str(r.get("grant_number", "")).strip()
            rows.append(_row(
                flow_id            = _fid(),
                flow_type          = "federal_cdbg_grant",
                source_system      = "hud_drgr",
                source_file        = "hud_drgr_projects.parquet",
                funding_source     = str(r.get("program_type", "HUD_CDBG_DR")).strip(),
                grant_number       = gn,
                disaster_number    = str(r.get("disaster_number", "")),
                applicant_or_grantee = str(r.get("grantee_name", "")).strip(),
                amount_type        = "grant_amount",
                amount             = str(r.get("grant_amount", "")),
                evidence_path      = "hud_drgr_projects.parquet",
            ))

    # Activity-level flows
    if not df_activities.empty:
        for _, r in df_activities.iterrows():
            gn = str(r.get("grant_number", "")).strip()
            rows.append(_row(
                flow_id            = _fid(),
                flow_type          = "hud_drgr_activity",
                source_system      = "hud_drgr",
                source_file        = "hud_drgr_activities.parquet",
                funding_source     = "HUD_DRGR",
                grant_number       = gn,
                activity_id        = str(r.get("activity_id", "")).strip(),
                applicant_or_grantee = "",
                responsible_organization = str(r.get("responsible_org", "")).strip(),
                amount_type        = "activity_budget",
                amount             = str(r.get("total_budget", "")),
                municipality       = str(r.get("municipality", r.get("county", ""))),
                evidence_path      = "hud_drgr_activities.parquet",
            ))

    # Drawdown-level flows
    if not df_drawdowns.empty:
        for _, r in df_drawdowns.iterrows():
            rows.append(_row(
                flow_id            = _fid(),
                flow_type          = "hud_drgr_drawdown",
                source_system      = "hud_drgr",
                source_file        = "hud_drgr_drawdowns.parquet",
                funding_source     = "HUD_DRGR",
                grant_number       = str(r.get("grant_number", "")),
                activity_id        = str(r.get("activity_id", "")),
                amount_type        = "drawdown",
                amount             = str(r.get("drawdown_amount", "")),
                drawdown_date      = str(r.get("drawdown_date", "")),
                evidence_path      = "hud_drgr_drawdowns.parquet",
            ))

    logger.info(f"  HUD DRGR: {len(rows):,} flow rows")
    return rows


def _ingest_cor3(df_cor3, logger):
    rows = []
    if df_cor3.empty:
        return rows
    for _, r in df_cor3.iterrows():
        rows.append(_row(
            flow_id            = _fid(),
            flow_type          = "pr_recovery_project",
            source_system      = "cor3",
            source_file        = "pr_cor3_projects.csv",
            funding_source     = str(r.get("program", "FEMA_PA")).strip(),
            project_id         = str(r.get("project_id", "")),
            applicant_or_grantee = str(r.get("applicant_name", "")),
            responsible_organization = str(r.get("applicant_name", "")),
            amount_type        = "total_approved",
            amount             = str(r.get("total_approved", "")),
            drawdown_date      = str(r.get("last_updated", "")),
            municipality       = str(r.get("municipality", "")),
            evidence_path      = "pr_cor3_projects.csv",
        ))
    logger.info(f"  COR3: {len(rows):,} flow rows")
    return rows


def _ingest_pr_procurement(df_prasa, df_compras, logger):
    rows = []
    for df, source_label, source_file in [
        (df_prasa,  "PRASA",   "pr_prasa_contracts.csv"),
        (df_compras, "Compras", "pr_compras_awards.csv"),
    ]:
        if df.empty:
            continue
        vendor_col = next((c for c in ["vendor_name", "awarded_vendor", "recipient_name"] if c in df.columns), None)
        amount_col = next((c for c in ["contract_value", "awarded_amount", "obligated_amount"] if c in df.columns), None)
        date_col   = next((c for c in ["award_date", "action_date"] if c in df.columns), None)
        id_col     = next((c for c in ["contract_id", "rfp_id", "award_id"] if c in df.columns), None)
        muni_col   = next((c for c in ["municipality", "pop_county"] if c in df.columns), None)
        for _, r in df.iterrows():
            rows.append(_row(
                flow_id            = _fid(),
                flow_type          = "pr_procurement",
                source_system      = source_label.lower(),
                source_file        = source_file,
                funding_source     = "PR_GOVERNMENT",
                prime_vendor       = str(r.get(vendor_col, "")) if vendor_col else "",
                amount_type        = "contract_value",
                amount             = str(r.get(amount_col, "")) if amount_col else "",
                award_date         = str(r.get(date_col, "")) if date_col else "",
                contract_id        = str(r.get(id_col, "")) if id_col else "",
                municipality       = str(r.get(muni_col, "")) if muni_col else "",
                evidence_path      = source_file,
            ))
    logger.info(f"  PR Procurement: {len(rows):,} flow rows")
    return rows


def _ingest_contracts(df_contracts, logger):
    rows = []
    if df_contracts.empty:
        return rows
    for _, r in df_contracts.iterrows():
        rows.append(_row(
            flow_id            = _fid(),
            flow_type          = "federal_contract",
            source_system      = str(r.get("source_dataset", "usaspending")).strip(),
            source_file        = "pr_contracts_master.csv",
            funding_source     = "FEDERAL",
            applicant_or_grantee = "",
            responsible_organization = "",
            prime_vendor       = str(r.get("recipient_name", "")),
            amount_type        = "obligated_amount",
            amount             = str(r.get("obligated_amount", "")),
            award_date         = str(r.get("award_date", "")),
            contract_id        = str(r.get("award_id", "")),
            municipality       = str(r.get("pop_county", "")),
            parent_uei         = str(r.get("recipient_uei", "")),
            evidence_path      = "pr_contracts_master.csv",
        ))
    logger.info(f"  Contracts: {len(rows):,} flow rows")
    return rows


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    norm_dir = root / "data" / "normalized"
    proc_dir = root / "data" / "staging" / "processed"
    linked_dir = root / "data" / "linked"
    norm_dir.mkdir(parents=True, exist_ok=True)

    out_path = norm_dir / "financial_flows_master.parquet"
    logger = setup_logging("build_financial_flows_master")

    if out_path.exists() and not force:
        rows = len(pd.read_parquet(out_path, engine="pyarrow"))
        logger.info(f"  financial_flows_master.parquet exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "status": "CACHED"}

    logger.info("Loading upstream inputs...")
    df_fema_v2      = _load_parquet(norm_dir / "fema_pa_projects_v2.parquet", logger)
    df_fema_portal  = _load_parquet(norm_dir / "fema_pa_portal_178_pws.parquet", logger)
    df_fema_linkage = _load_csv(linked_dir / "fema_178_pw_linkage.csv", logger)
    df_hud_projects = _load_parquet(norm_dir / "hud_drgr_projects.parquet", logger)
    df_hud_acts     = _load_parquet(norm_dir / "hud_drgr_activities.parquet", logger)
    df_hud_draws    = _load_parquet(norm_dir / "hud_drgr_drawdowns.parquet", logger)
    df_cor3         = _load_csv(proc_dir / "pr_cor3_projects.csv", logger)
    df_prasa        = _load_csv(proc_dir / "pr_prasa_contracts.csv", logger)
    df_compras      = _load_csv(proc_dir / "pr_compras_awards.csv", logger)
    df_contracts    = _load_csv(proc_dir / "pr_contracts_master.csv", logger)
    if df_contracts.empty:
        df_contracts = _load_csv(proc_dir / "pr_all_awards_master.csv", logger)

    all_rows = []
    all_rows.extend(_ingest_fema_pa(df_fema_v2, df_fema_portal, df_fema_linkage, logger))
    all_rows.extend(_ingest_hud_drgr(df_hud_projects, df_hud_acts, df_hud_draws, logger))
    all_rows.extend(_ingest_cor3(df_cor3, logger))
    all_rows.extend(_ingest_pr_procurement(df_prasa, df_compras, logger))
    all_rows.extend(_ingest_contracts(df_contracts, logger))

    if all_rows:
        df_out = pd.DataFrame(all_rows, columns=FLOW_COLUMNS)
    else:
        logger.warning("  No upstream data found — writing empty financial_flows_master")
        df_out = pd.DataFrame(columns=FLOW_COLUMNS)

    df_out.to_parquet(out_path, index=False, engine="pyarrow")

    total_amount = pd.to_numeric(df_out["amount"], errors="coerce").fillna(0).sum()
    flow_types = df_out["flow_type"].value_counts().to_dict() if not df_out.empty else {}

    logger.info("=" * 60)
    logger.info("FINANCIAL FLOWS MASTER SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total flow rows:  {len(df_out):,}")
    logger.info(f"  Total amount:     ${total_amount:,.0f}")
    for ftype, count in sorted(flow_types.items(), key=lambda x: -x[1]):
        logger.info(f"    {ftype}: {count:,}")
    logger.info(f"  → {out_path.name}")

    return {"rows": len(df_out), "total_amount": total_amount, "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Build financial flows master parquet")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFinancial flows master: {result['rows']:,} rows, "
          f"${result.get('total_amount', 0):,.0f} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
