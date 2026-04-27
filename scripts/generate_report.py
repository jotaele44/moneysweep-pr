"""
Synthesize all pipeline outputs into a single investigative report.

Reads every processed CSV and produces:
  data/reports/pr_investigative_report.md  — human-readable markdown
  data/reports/pr_report_summary.json      — structured JSON for programmatic use

Works gracefully with partial data: sections backed by empty or missing files
are clearly marked as "pending data" rather than crashing.

Core investigative questions answered:
  1. Federal money concentration — who receives the most, from which agencies?
  2. Top influence actors — 7-axis power network ranking
  3. Prime-to-subcontractor flows — who controls the subcontracting layer?
  4. Full-loop entities — awards + FEC contributions + LDA lobbying simultaneously
  5. High-risk delivery — contractors with low FEMA completion / EQB violations
  6. RFP-lobby influence — procurements where winner had prior lobbying activity
  7. Dual-role bond actors — federal contractors who also underwrite PR bonds
  8. OFAC sanctions matches — award recipients on the SDN list
  9. SF-133 obligation gaps — federal money sitting unspent by agency

Usage:
  python3 scripts/generate_report.py
  python3 scripts/generate_report.py --force
  python3 scripts/generate_report.py --top 25
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOP_N_DEFAULT = 20
CURRENCY_THRESHOLD = 1_000_000  # only show entities with >$1M in awards

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: Path, label: str, logger) -> pd.DataFrame:
    if not path.exists():
        logger.info(f"  {label}: not found — section will show pending status")
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, low_memory=False)
    real_rows = len(df)
    logger.info(f"  {label}: {real_rows:,} rows")
    return df


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def _fmt_usd(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


def _pending(label: str) -> str:
    return f"*{label} — data pending; run pipeline from Mac to populate.*\n"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_awards(entity_df: pd.DataFrame, top_n: int) -> tuple[str, dict]:
    if entity_df.empty:
        return _pending("Federal award concentration"), {}

    entity_df = entity_df.copy()
    entity_df["_obl"] = _num(entity_df, "total_obligated")
    entity_df["_cnt"] = _num(entity_df, "award_count")

    total = entity_df["_obl"].sum()
    n_entities = len(entity_df)
    top = entity_df.nlargest(top_n, "_obl")

    top10_share = entity_df.nlargest(10, "_obl")["_obl"].sum() / total if total > 0 else 0

    lines = [
        f"**Total obligated (all datasets):** {_fmt_usd(total)}  ",
        f"**Unique award recipients:** {n_entities:,}  ",
        f"**Top-10 concentration:** {top10_share:.1%} of total  \n",
        f"| # | Entity | Total Obligated | Awards | Datasets | FY Range |",
        f"|---|--------|----------------|--------|----------|----------|",
    ]
    for i, (_, row) in enumerate(top.iterrows(), 1):
        datasets = str(row.get("source_datasets") or "")
        n_ds = len([d for d in datasets.split("|") if d])
        lines.append(
            f"| {i} | {str(row.get('canonical_name',''))[:55]} "
            f"| {_fmt_usd(row['_obl'])} "
            f"| {int(row['_cnt']):,} "
            f"| {n_ds} "
            f"| {row.get('fiscal_year_range','?')} |"
        )

    summary = {
        "total_obligated": float(total),
        "unique_entities": n_entities,
        "top10_share": round(float(top10_share), 4),
        "top_entities": [
            {"name": str(r.get("canonical_name","")), "obligated": float(r["_obl"])}
            for _, r in top.head(10).iterrows()
        ],
    }
    return "\n".join(lines) + "\n", summary


def _section_power_network(net_df: pd.DataFrame, top_n: int) -> tuple[str, dict]:
    if net_df.empty:
        return _pending("Influence power network"), {}

    net_df = net_df.copy()
    net_df["_score"] = _num(net_df, "influence_score")
    net_df["_awards"] = _num(net_df, "awards_total")
    net_df["_presence"] = _num(net_df, "source_presence")

    top = net_df.nlargest(top_n, "_score")
    full_loop = net_df[
        (_num(net_df, "fec_total_contributions") > 0) &
        (_num(net_df, "lda_lobbying_total") > 0) &
        (net_df["_awards"] > 0)
    ]
    bond_actors = net_df[_num(net_df, "bond_total_par") > 0] if "bond_total_par" in net_df.columns else pd.DataFrame()

    lines = [
        f"**Entities ranked:** {len(net_df):,}  ",
        f"**Full-loop entities** (awards + FEC + lobbying): {len(full_loop):,}  ",
        f"**Bond market actors in network:** {len(bond_actors):,}  \n",
        f"| Rank | Entity | Score | Awards | Sources | Bond Par |",
        f"|------|--------|-------|--------|---------|----------|",
    ]
    for _, row in top.iterrows():
        sources = []
        if float(row.get("fec_total_contributions") or 0) > 0: sources.append("FEC")
        if float(row.get("lda_lobbying_total") or 0) > 0:      sources.append("LDA")
        if float(row.get("np_revenue") or 0) > 0:              sources.append("990")
        if float(row.get("cms_medicare_payment") or 0) > 0:    sources.append("CMS")
        if float(row.get("bond_total_par") or 0) > 0:          sources.append("Bond")
        bond_par = _fmt_usd(row.get("bond_total_par") or 0)
        lines.append(
            f"| {int(row.get('rank',0))} "
            f"| {str(row.get('canonical_name',''))[:52]} "
            f"| {float(row['_score']):.1f} "
            f"| {_fmt_usd(row['_awards'])} "
            f"| {', '.join(sources) or '—'} "
            f"| {bond_par} |"
        )

    if not full_loop.empty:
        lines += [
            "\n**Full-loop entities (awards + FEC contributions + LDA lobbying):**\n",
            "| Entity | Awards | FEC | Lobbying |",
            "|--------|--------|-----|---------|",
        ]
        for _, row in full_loop.nlargest(10, "_awards").iterrows():
            lines.append(
                f"| {str(row.get('canonical_name',''))[:50]} "
                f"| {_fmt_usd(row['_awards'])} "
                f"| {_fmt_usd(row.get('fec_total_contributions') or 0)} "
                f"| {_fmt_usd(row.get('lda_lobbying_total') or 0)} |"
            )

    summary = {
        "total_ranked": len(net_df),
        "full_loop_count": len(full_loop),
        "bond_actors_count": len(bond_actors),
        "top_entities": [
            {
                "rank": int(r.get("rank", 0)),
                "name": str(r.get("canonical_name", "")),
                "score": float(r["_score"]),
                "awards": float(r["_awards"]),
            }
            for _, r in top.head(10).iterrows()
        ],
    }
    return "\n".join(lines) + "\n", summary


def _section_prime_sub(ps_df: pd.DataFrame, top_n: int) -> tuple[str, dict]:
    if ps_df.empty:
        return _pending("Prime-to-subcontractor flows"), {}

    ps_df = ps_df.copy()
    ps_df["_flow"] = _num(ps_df, "total_flow")

    total_flow = ps_df["_flow"].sum()
    unique_primes = ps_df["prime_recipient"].nunique() if "prime_recipient" in ps_df.columns else 0
    unique_subs   = ps_df["sub_recipient"].nunique()   if "sub_recipient" in ps_df.columns else 0

    top = ps_df.nlargest(top_n, "_flow")

    lines = [
        f"**Total subcontract flow:** {_fmt_usd(total_flow)}  ",
        f"**Unique prime contractors:** {unique_primes:,}  ",
        f"**Unique subcontractors:** {unique_subs:,}  \n",
        f"| Prime | Subcontractor | Flow | Contracts |",
        f"|-------|--------------|------|-----------|",
    ]
    for _, row in top.iterrows():
        lines.append(
            f"| {str(row.get('prime_recipient',''))[:40]} "
            f"| {str(row.get('sub_recipient',''))[:40]} "
            f"| {_fmt_usd(row['_flow'])} "
            f"| {int(float(row.get('contract_count',0)))} |"
        )

    summary = {
        "total_flow": float(total_flow),
        "unique_primes": unique_primes,
        "unique_subs": unique_subs,
        "top_pairs": [
            {
                "prime": str(r.get("prime_recipient", "")),
                "sub": str(r.get("sub_recipient", "")),
                "flow": float(r["_flow"]),
            }
            for _, r in top.head(10).iterrows()
        ],
    }
    return "\n".join(lines) + "\n", summary


def _section_delivery(delivery_df: pd.DataFrame, top_n: int) -> tuple[str, dict]:
    if delivery_df.empty:
        return _pending("Project delivery scorecard"), {}

    delivery_df = delivery_df.copy()
    delivery_df["_score"] = _num(delivery_df, "delivery_score")

    high_risk   = delivery_df[delivery_df.get("risk_tier", pd.Series()) == "high"]
    medium_risk = delivery_df[delivery_df.get("risk_tier", pd.Series()) == "medium"]

    lines = [
        f"**Entities scored:** {len(delivery_df):,}  ",
        f"**High risk** (score < 40): {len(high_risk):,}  ",
        f"**Medium risk** (score 40–70): {len(medium_risk):,}  \n",
    ]
    if not high_risk.empty:
        lines += [
            "**High-risk contractors:**\n",
            "| Entity | Score | FEMA Rate | COR3 Rate | USACE OK | EQB Violations |",
            "|--------|-------|-----------|-----------|----------|----------------|",
        ]
        for _, row in high_risk.nlargest(top_n, "total_awards_obligated" if "total_awards_obligated" in delivery_df.columns else "_score").iterrows():
            lines.append(
                f"| {str(row.get('canonical_name',''))[:45]} "
                f"| {float(row['_score']):.0f} "
                f"| {float(row.get('fema_completion_rate') or 0):.0%} "
                f"| {float(row.get('cor3_disbursement_rate') or 0):.0%} "
                f"| {'✓' if int(float(row.get('usace_permit_ok') or 0)) else '✗'} "
                f"| {int(float(row.get('eqb_violations') or 0))} |"
            )

    summary = {
        "total_scored": len(delivery_df),
        "high_risk_count": len(high_risk),
        "medium_risk_count": len(medium_risk),
        "high_risk_entities": [str(r.get("canonical_name","")) for _, r in high_risk.head(10).iterrows()],
    }
    return "\n".join(lines) + "\n", summary


def _section_rfp_lobby(rfp_df: pd.DataFrame, top_n: int) -> tuple[str, dict]:
    if rfp_df.empty:
        return _pending("RFP × lobbying cross-reference"), {}

    rfp_df = rfp_df.copy()
    rfp_df["_iscore"] = _num(rfp_df, "influence_score")
    flagged = rfp_df[_num(rfp_df, "lda_flag") > 0]

    lines = [
        f"**Total RFPs analyzed:** {len(rfp_df):,}  ",
        f"**RFPs with prior winner lobbying:** {len(flagged):,} ({len(flagged)/len(rfp_df):.1%})  \n",
    ]
    if not flagged.empty:
        lines += [
            "| RFP Title | Agency | Awarded To | Influence Score | Lobby Lead Days | LDA Spend |",
            "|-----------|--------|-----------|----------------|----------------|-----------|",
        ]
        for _, row in flagged.nlargest(top_n, "_iscore").iterrows():
            lines.append(
                f"| {str(row.get('title',''))[:45]} "
                f"| {str(row.get('agency',''))[:30]} "
                f"| {str(row.get('awarded_vendor',''))[:35]} "
                f"| {float(row['_iscore']):.3f} "
                f"| {row.get('lobby_lead_days','?')} "
                f"| {_fmt_usd(row.get('lda_spend_prior_window') or 0)} |"
            )

    summary = {
        "total_rfps": len(rfp_df),
        "flagged_rfps": len(flagged),
        "flagged_share": round(len(flagged)/len(rfp_df), 4) if rfp_df.shape[0] > 0 else 0,
    }
    return "\n".join(lines) + "\n", summary


def _section_bond_flow(bond_df: pd.DataFrame, top_n: int) -> tuple[str, dict]:
    if bond_df.empty:
        return _pending("Bond market financial flow"), {}

    bond_df = bond_df.copy()
    dual = bond_df[_num(bond_df, "is_dual_role") > 0]
    issuers = bond_df[_num(bond_df, "bond_issuer_flag") > 0]
    uw = bond_df[_num(bond_df, "bond_underwriter_flag") > 0]

    lines = [
        f"**Entities with bond market presence:** {(bond_df[['bond_issuer_flag','bond_underwriter_flag','bond_dealer_flag']].apply(lambda c: _num(bond_df, c.name) > 0).any(axis=1)).sum():,}  ",
        f"**Dual-role** (federal contractor + bond market): {len(dual):,}  ",
        f"**Bond issuers** in entity master: {len(issuers):,}  ",
        f"**Underwriters** in entity master: {len(uw):,}  \n",
    ]
    if not dual.empty:
        lines += [
            "**Dual-role entities — federal awards AND bond underwriting/dealing:**\n",
            "| Entity | Federal Awards | Underwriting Par | Dealer Volume | Est. UW Fee |",
            "|--------|---------------|-----------------|--------------|-------------|",
        ]
        for _, row in dual.nlargest(top_n, "dual_role_awards").iterrows():
            lines.append(
                f"| {str(row.get('canonical_name',''))[:50]} "
                f"| {_fmt_usd(row.get('dual_role_awards') or 0)} "
                f"| {_fmt_usd(row.get('bonds_underwritten_par') or 0)} "
                f"| {_fmt_usd(row.get('dealer_volume_par') or 0)} "
                f"| {_fmt_usd(row.get('estimated_underwriter_fee') or 0)} |"
            )

    summary = {
        "dual_role_count": len(dual),
        "issuer_count": len(issuers),
        "underwriter_count": len(uw),
        "dual_role_entities": [str(r.get("canonical_name","")) for _, r in dual.head(10).iterrows()],
    }
    return "\n".join(lines) + "\n", summary


def _section_ofac(ofac_df: pd.DataFrame) -> tuple[str, dict]:
    if ofac_df.empty:
        return _pending("OFAC SDN sanctions cross-reference"), {}

    matches = ofac_df[_num(ofac_df, "obligated_amount") > 0] if "obligated_amount" in ofac_df.columns else ofac_df

    lines = [f"**SDN matches against award recipients:** {len(ofac_df):,}  \n"]
    if not ofac_df.empty:
        lines += [
            "| Award Recipient | SDN Name | Obligated | Match Score |",
            "|----------------|---------|-----------|-------------|",
        ]
        for _, row in ofac_df.head(20).iterrows():
            lines.append(
                f"| {str(row.get('recipient_name',''))[:45]} "
                f"| {str(row.get('sdn_name', row.get('name','?')))[:40]} "
                f"| {_fmt_usd(row.get('obligated_amount') or 0)} "
                f"| {float(row.get('match_score') or 0):.2f} |"
            )

    summary = {"match_count": len(ofac_df)}
    return "\n".join(lines) + "\n", summary


def _section_sf133(sf_df: pd.DataFrame, top_n: int) -> tuple[str, dict]:
    if sf_df.empty:
        return _pending("SF-133 federal budget execution"), {}

    sf_df = sf_df.copy()
    sf_df["_obl_rate"] = _num(sf_df, "obligation_rate")
    sf_df["_budget"]   = _num(sf_df, "budget_authority")

    low_obl = sf_df[sf_df["_obl_rate"] < 0.5].nlargest(top_n, "_budget")
    total_budget = sf_df["_budget"].sum()
    total_obligations = _num(sf_df, "obligations").sum()
    avg_rate = total_obligations / total_budget if total_budget > 0 else 0

    lines = [
        f"**Total budget authority:** {_fmt_usd(total_budget)}  ",
        f"**Total obligations:** {_fmt_usd(total_obligations)}  ",
        f"**Average obligation rate:** {avg_rate:.1%}  \n",
        f"**Low-obligation accounts (<50% obligated) — largest unspent balances:**\n",
        f"| Agency | Account | Budget | Obligation Rate | Unobligated |",
        f"|--------|---------|--------|----------------|-------------|",
    ]
    for _, row in low_obl.iterrows():
        lines.append(
            f"| {str(row.get('agency_name',''))[:10]} "
            f"| {str(row.get('account_title',''))[:50]} "
            f"| {_fmt_usd(row['_budget'])} "
            f"| {float(row['_obl_rate']):.1%} "
            f"| {_fmt_usd(row.get('unobligated_balance') or 0)} |"
        )

    summary = {
        "total_budget": float(total_budget),
        "total_obligations": float(total_obligations),
        "avg_obligation_rate": round(float(avg_rate), 4),
        "low_obligation_accounts": len(low_obl),
    }
    return "\n".join(lines) + "\n", summary


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False, top_n: int = TOP_N_DEFAULT) -> dict:
    root = Path(root or PROJECT_ROOT)
    proc = root / "data" / "staging" / "processed"
    reports_dir = root / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path  = reports_dir / "pr_investigative_report.md"
    summary_path = reports_dir / "pr_report_summary.json"

    logger = setup_logging("generate_report", log_dir=root / "data" / "logs")

    if report_path.exists() and not force:
        logger.info(f"  Report exists — skipping (use --force to regenerate).")
        return {"status": "CACHED", "report_path": str(report_path)}

    logger.info("Loading pipeline outputs...")
    entity_df   = _load(proc / "entity_master.csv",             "entity_master",       logger)
    net_df      = _load(proc / "pr_power_network.csv",          "power_network",       logger)
    ps_df       = _load(proc / "pr_prime_sub_relationships.csv","prime_sub",           logger)
    delivery_df = _load(proc / "pr_delivery_scorecard.csv",     "delivery_scorecard",  logger)
    rfp_df      = _load(proc / "pr_rfp_lobby_crossref.csv",     "rfp_lobby_crossref",  logger)
    bond_df     = _load(proc / "pr_bond_flow.csv",              "bond_flow",           logger)
    ofac_df     = _load(proc / "pr_ofac_matches.csv",           "ofac_matches",        logger)
    sf133_df    = _load(proc / "pr_sf133_budget_execution.csv", "sf133",               logger)

    # Build each section
    s_awards,   j_awards   = _section_awards(entity_df, top_n)
    s_network,  j_network  = _section_power_network(net_df, top_n)
    s_primesub, j_primesub = _section_prime_sub(ps_df, top_n)
    s_delivery, j_delivery = _section_delivery(delivery_df, top_n)
    s_rfplob,   j_rfplob   = _section_rfp_lobby(rfp_df, top_n)
    s_bond,     j_bond     = _section_bond_flow(bond_df, top_n)
    s_ofac,     j_ofac     = _section_ofac(ofac_df)
    s_sf133,    j_sf133    = _section_sf133(sf133_df, top_n)

    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    data_layers = sum([
        not entity_df.empty, not net_df.empty, not ps_df.empty,
        not delivery_df.empty, not rfp_df.empty, not bond_df.empty,
        not ofac_df.empty, not sf133_df.empty,
    ])

    # Assemble markdown report
    report = f"""# Puerto Rico Federal Contract Ecosystem — Investigative Report

*Generated: {generated_at}*
*Data layers populated: {data_layers}/8 — sections marked "pending" require a Mac pipeline run.*

---

## 1. Federal Money Concentration

{s_awards}
---

## 2. Integrated Influence Power Network

{s_network}
---

## 3. Prime-to-Subcontractor Flows

{s_primesub}
---

## 4. Project Delivery Risk

{s_delivery}
---

## 5. RFP × Lobbying Influence

{s_rfplob}
---

## 6. Municipal Bond Financial Flow

{s_bond}
---

## 7. OFAC Sanctions Matches

{s_ofac}
---

## 8. SF-133 Federal Budget Execution

{s_sf133}
---

## Data Coverage

| Layer | Status |
|-------|--------|
| Federal awards master | {'✅' if not entity_df.empty else '⏳ pending Mac run'} |
| Power network (7-axis) | {'✅' if not net_df.empty else '⏳ pending Mac run'} |
| Prime-sub relationships | {'✅' if not ps_df.empty else '⏳ pending Mac run'} |
| Delivery scorecard | {'✅' if not delivery_df.empty else '⏳ pending Mac run'} |
| RFP-lobby crossref | {'✅' if not rfp_df.empty else '⏳ pending Mac run'} |
| Bond financial flow | {'✅' if not bond_df.empty else '⏳ pending Mac run'} |
| OFAC sanctions | {'✅' if not ofac_df.empty else '⏳ pending Mac run'} |
| SF-133 budget execution | {'✅' if not sf133_df.empty else '⏳ pending Mac run'} |

*To populate all layers: `python3 run_all.py --skip-download` from a machine with unrestricted network access.*
"""

    report_path.write_text(report, encoding="utf-8")
    logger.info(f"  Written: {report_path.name}")

    summary = {
        "generated_at":    generated_at,
        "data_layers":     data_layers,
        "awards":          j_awards,
        "power_network":   j_network,
        "prime_sub":       j_primesub,
        "delivery":        j_delivery,
        "rfp_lobby":       j_rfplob,
        "bond_flow":       j_bond,
        "ofac":            j_ofac,
        "sf133":           j_sf133,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  Written: {summary_path.name}")

    logger.info(f"  Report complete — {data_layers}/8 data layers populated")

    return {
        "status":       "OK",
        "data_layers":  data_layers,
        "report_path":  str(report_path),
        "summary_path": str(summary_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate PR investigative report from all pipeline outputs"
    )
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if report already exists")
    parser.add_argument("--top", type=int, default=TOP_N_DEFAULT,
                        help=f"Number of top entities per section (default: {TOP_N_DEFAULT})")
    args = parser.parse_args()
    result = run(force=args.force, top_n=args.top)
    if result.get("status") in ("OK", "CACHED"):
        print(f"\nReport: {result.get('report_path','')}")
        print(f"Summary: {result.get('summary_path','')}")
        if result.get("data_layers") is not None:
            print(f"Data layers: {result['data_layers']}/8")
    return 0 if result.get("status") in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
