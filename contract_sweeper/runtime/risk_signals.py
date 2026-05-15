"""Phase 7 risk signal engine for Puerto Rico contract/spending data.

Computes deterministic risk signals against R5 output shapes.
Every signal cites source rows; every score is explainable.
Missing data reduces confidence; no silent inference.

Signal families:
  concentration       — entity dominates award share
  repeat_awards       — entity receives unusually many awards
  subaward_opacity    — execution chain has low visibility
  parent_sub_mismatch — prime and sub share corporate parent (related party)
  political_overlap   — awardee also appears in lobbying/FEC records
  bond_contract_overlap — bond issuer is also contract recipient
  geographic_clustering — single municipality dominates award spend
  stale_lineage       — award record lacks provenance fields

Outputs (written by scripts/build_risk_signals.py):
  data/staging/processed/risk/risk_signals_master.csv
  data/staging/processed/risk/entity_risk_scores.csv
  data/staging/processed/risk/project_risk_scores.csv
  data/staging/processed/risk/municipality_risk_scores.csv
  data/manifests/risk_signal_report.json
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from contract_sweeper.runtime.source_registry import REPO_ROOT

# ---------- Paths ----------
PROCESSED = REPO_ROOT / "data" / "staging" / "processed"
RISK_OUT   = PROCESSED / "risk"

AWARDS_PATH     = PROCESSED / "pr_all_awards_master.csv"
CHAINS_PATH     = PROCESSED / "execution" / "execution_chain_master.csv"
ENTITIES_PATH   = PROCESSED / "entities_resolved.csv"
SUBAWARDS_PATH  = PROCESSED / "pr_subawards_master.csv"
EMMA_PATH       = PROCESSED / "pr_emma_bonds.csv"
LDA_PATH        = PROCESSED / "pr_lda_filings.csv"
FEC_PATH        = PROCESSED / "pr_fec_contributions.csv"
CABILDEROS_PATH = PROCESSED / "pr_cabilderos.csv"

# ---------- Thresholds (single source of truth) ----------
CONCENTRATION_THRESHOLD  = 0.15   # entity > 15% of total award spend
REPEAT_AWARD_THRESHOLD   = 3      # entity has ≥ 3 separate awards
OPACITY_CONFIDENCE_MIN   = 0.80   # chain link_confidence below this = opacity flag
GEO_CLUSTER_THRESHOLD    = 0.30   # municipality > 30% of award count
LINEAGE_REQUIRED_FIELDS  = ("source_lineage_path", "source_dataset", "source_record_id")

SCHEMA_VERSION = "r7_v1"


# ---------- Helpers ----------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(name: str) -> str:
    """Lightweight name normalizer for cross-source matching."""
    import re
    if not name:
        return ""
    s = name.upper().strip()
    # Remove common suffixes
    for suffix in (" LLC", " INC", " CORP", " LTD", " L.L.C.", " INC.", " CO.", " S.E."):
        s = s.replace(suffix, "")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _to_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(",", "").strip() or default)
    except (ValueError, TypeError):
        return default


def _read_csv(path: Path | str, root: Path | None = None) -> pd.DataFrame:
    """Read CSV gracefully; return empty DataFrame on missing/empty file."""
    p = Path(path)
    if root:
        p = root / path
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(p, dtype=str, na_filter=False, low_memory=False)
        return df if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _signal_id(family: str, subject_id: str, seq: int) -> str:
    return f"SIG-{family[:4].upper()}-{str(subject_id)[:12].replace(' ', '_')}-{seq:04d}"


# ---------- Signal computers ----------

def _signals_concentration(awards: pd.DataFrame) -> list[dict]:
    signals: list[dict] = []
    if awards.empty:
        return signals

    awards = awards.copy()
    awards["_amount"] = awards.get("obligated_amount", pd.Series(dtype=str)).apply(_to_float)
    total = awards["_amount"].sum()
    if total <= 0:
        return signals

    col = "recipient_name_normalized" if "recipient_name_normalized" in awards.columns else "recipient_name"
    grouped = awards.groupby(col)["_amount"].sum().sort_values(ascending=False)

    for seq, (name, amount) in enumerate(grouped.items()):
        pct = amount / total
        if pct < CONCENTRATION_THRESHOLD:
            continue
        rows = awards[awards[col] == name]
        award_ids = ";".join(rows.get("award_id", pd.Series(dtype=str)).tolist()[:15])
        signals.append({
            "signal_id":       _signal_id("concentration", name, seq),
            "signal_family":   "concentration",
            "signal_type":     "entity_award_concentration",
            "severity":        "high" if pct >= 0.40 else "medium",
            "subject_type":    "entity",
            "subject_id":      _normalize(name),
            "entity_name":     name,
            "signal_value":    round(pct, 6),
            "threshold":       CONCENTRATION_THRESHOLD,
            "confidence":      0.90,
            "evidence_source": "pr_all_awards_master",
            "evidence_row_ids": award_ids,
            "explanation":     (
                f"{name} received {pct:.1%} of total PR award spend "
                f"(${amount:,.0f} of ${total:,.0f})"
            ),
        })
    return signals


def _signals_repeat_awards(awards: pd.DataFrame) -> list[dict]:
    signals: list[dict] = []
    if awards.empty:
        return signals

    col = "recipient_name_normalized" if "recipient_name_normalized" in awards.columns else "recipient_name"
    counts = awards.groupby(col).size()

    for seq, (name, count) in enumerate(counts[counts >= REPEAT_AWARD_THRESHOLD].items()):
        rows = awards[awards[col] == name]
        award_ids = ";".join(rows.get("award_id", pd.Series(dtype=str)).tolist()[:15])
        signals.append({
            "signal_id":       _signal_id("repeat_awards", name, seq),
            "signal_family":   "repeat_awards",
            "signal_type":     "repeat_award_recipient",
            "severity":        "medium",
            "subject_type":    "entity",
            "subject_id":      _normalize(name),
            "entity_name":     name,
            "signal_value":    float(count),
            "threshold":       float(REPEAT_AWARD_THRESHOLD),
            "confidence":      0.85,
            "evidence_source": "pr_all_awards_master",
            "evidence_row_ids": award_ids,
            "explanation":     f"{name} received {count} separate awards",
        })
    return signals


def _signals_subaward_opacity(chains: pd.DataFrame) -> list[dict]:
    signals: list[dict] = []
    if chains.empty:
        return signals

    for seq, row in enumerate(chains.to_dict("records")):
        flags: list[str] = []
        sub_uei = str(row.get("sub_uei", "")).strip()
        if not sub_uei:
            flags.append("missing_sub_uei")

        confidence = _to_float(row.get("link_confidence", 1.0), 1.0)
        if confidence < OPACITY_CONFIDENCE_MIN:
            flags.append(f"low_link_confidence:{confidence:.2f}")

        manual = str(row.get("manual_review_required", "")).lower()
        if manual in ("true", "1", "yes"):
            flags.append("manual_review_required")

        if not flags:
            continue

        prime = str(row.get("prime_name", ""))
        sub = str(row.get("sub_name", ""))
        signals.append({
            "signal_id":       _signal_id("subaward_opacity", row.get("chain_id", str(seq)), seq),
            "signal_family":   "subaward_opacity",
            "signal_type":     "chain_opacity",
            "severity":        "high" if "missing_sub_uei" in flags else "medium",
            "subject_type":    "chain",
            "subject_id":      str(row.get("chain_id", "")),
            "entity_name":     prime,
            "signal_value":    confidence,
            "threshold":       OPACITY_CONFIDENCE_MIN,
            "confidence":      max(0.1, confidence),
            "evidence_source": "execution_chain_master",
            "evidence_row_ids": str(row.get("chain_id", "")),
            "explanation":     (
                f"Chain {row.get('chain_id','')} ({prime} → {sub}) "
                f"has opacity flags: {', '.join(flags)}"
            ),
        })
    return signals


def _signals_parent_sub_mismatch(chains: pd.DataFrame) -> list[dict]:
    """Flag chains where prime and sub share the same corporate parent (related-party risk)."""
    signals: list[dict] = []
    if chains.empty:
        return signals

    for seq, row in enumerate(chains.to_dict("records")):
        p_parent = str(row.get("prime_parent_uei", "")).strip()
        s_parent = str(row.get("sub_parent_uei", "")).strip()
        if not p_parent or not s_parent:
            continue
        if p_parent == s_parent:
            prime = str(row.get("prime_name", ""))
            sub   = str(row.get("sub_name", ""))
            signals.append({
                "signal_id":       _signal_id("parent_sub_mismatch", row.get("chain_id", str(seq)), seq),
                "signal_family":   "parent_sub_mismatch",
                "signal_type":     "shared_corporate_parent",
                "severity":        "high",
                "subject_type":    "chain",
                "subject_id":      str(row.get("chain_id", "")),
                "entity_name":     prime,
                "signal_value":    1.0,
                "threshold":       0.0,
                "confidence":      0.95,
                "evidence_source": "execution_chain_master",
                "evidence_row_ids": str(row.get("chain_id", "")),
                "explanation":     (
                    f"{prime} and {sub} share corporate parent UEI {p_parent} — "
                    "possible related-party subcontract"
                ),
            })
    return signals


def _signals_political_overlap(
    awards: pd.DataFrame,
    lda: pd.DataFrame,
    fec: pd.DataFrame,
    cabilderos: pd.DataFrame,
) -> list[dict]:
    signals: list[dict] = []
    if awards.empty:
        return signals

    col = "recipient_name_normalized" if "recipient_name_normalized" in awards.columns else "recipient_name"
    award_names: dict[str, list[str]] = {}
    for _, row in awards.iterrows():
        norm = _normalize(str(row.get(col, "")))
        award_id = str(row.get("award_id", ""))
        if norm:
            award_names.setdefault(norm, []).append(award_id)

    seq = 0

    # LDA: lobbying clients who are also awardees
    if not lda.empty:
        for _, row in lda.iterrows():
            client_norm = _normalize(str(row.get("client_name", "")))
            if client_norm in award_names:
                filing = str(row.get("filing_uuid", ""))
                signals.append({
                    "signal_id":       _signal_id("political_overlap", client_norm, seq),
                    "signal_family":   "political_overlap",
                    "signal_type":     "lobbying_client_is_awardee",
                    "severity":        "medium",
                    "subject_type":    "entity",
                    "subject_id":      client_norm,
                    "entity_name":     str(row.get("client_name", "")),
                    "signal_value":    1.0,
                    "threshold":       0.0,
                    "confidence":      0.80,
                    "evidence_source": "pr_lda_filings;pr_all_awards_master",
                    "evidence_row_ids": f"lda:{filing};awards:{';'.join(award_names[client_norm][:5])}",
                    "explanation":     (
                        f"{row.get('client_name','')} appears in LDA lobbying registry "
                        f"(registrant: {row.get('registrant_name','')}) "
                        f"and received PR awards"
                    ),
                })
                seq += 1

    # PR Cabilderos: local lobbying clients who are awardees
    if not cabilderos.empty:
        for _, row in cabilderos.iterrows():
            client_norm = _normalize(str(row.get("client_normalized", row.get("client_name", ""))))
            if client_norm in award_names:
                signals.append({
                    "signal_id":       _signal_id("political_overlap", client_norm, seq),
                    "signal_family":   "political_overlap",
                    "signal_type":     "pr_lobbying_client_is_awardee",
                    "severity":        "medium",
                    "subject_type":    "entity",
                    "subject_id":      client_norm,
                    "entity_name":     str(row.get("client_name", "")),
                    "signal_value":    1.0,
                    "threshold":       0.0,
                    "confidence":      0.80,
                    "evidence_source": "pr_cabilderos;pr_all_awards_master",
                    "evidence_row_ids": f"cabilderos:{row.get('lobbyist_name','')};awards:{';'.join(award_names[client_norm][:5])}",
                    "explanation":     (
                        f"{row.get('client_name','')} registered PR lobbyist client "
                        f"(lobbyist: {row.get('lobbyist_name','')}) and received PR awards"
                    ),
                })
                seq += 1

    # FEC: employers/contributors who are awardees
    if not fec.empty:
        for _, row in fec.iterrows():
            employer_norm = _normalize(str(row.get("contributor_employer", "")))
            if employer_norm and employer_norm in award_names:
                signals.append({
                    "signal_id":       _signal_id("political_overlap", employer_norm, seq),
                    "signal_family":   "political_overlap",
                    "signal_type":     "fec_contributor_employer_is_awardee",
                    "severity":        "low",
                    "subject_type":    "entity",
                    "subject_id":      employer_norm,
                    "entity_name":     str(row.get("contributor_employer", "")),
                    "signal_value":    _to_float(row.get("contribution_receipt_amount", 0)),
                    "threshold":       0.0,
                    "confidence":      0.60,
                    "evidence_source": "pr_fec_contributions;pr_all_awards_master",
                    "evidence_row_ids": f"fec:{row.get('contributor_name','')};awards:{';'.join(award_names[employer_norm][:5])}",
                    "explanation":     (
                        f"{row.get('contributor_employer','')} FEC contributor employer "
                        f"matches PR award recipient"
                    ),
                })
                seq += 1

    return signals


def _signals_bond_contract_overlap(awards: pd.DataFrame, emma: pd.DataFrame) -> list[dict]:
    signals: list[dict] = []
    if awards.empty or emma.empty:
        return signals

    col = "recipient_name_normalized" if "recipient_name_normalized" in awards.columns else "recipient_name"
    award_names: dict[str, list[str]] = {}
    for _, row in awards.iterrows():
        norm = _normalize(str(row.get(col, "")))
        if norm:
            award_names.setdefault(norm, []).append(str(row.get("award_id", "")))

    for seq, (_, row) in enumerate(emma.iterrows()):
        issuer_norm = _normalize(str(row.get("issuer_name", "")))
        if issuer_norm not in award_names:
            continue
        par = _to_float(row.get("par_amount", 0))
        signals.append({
            "signal_id":       _signal_id("bond_contract_overlap", issuer_norm, seq),
            "signal_family":   "bond_contract_overlap",
            "signal_type":     "bond_issuer_is_contract_recipient",
            "severity":        "medium",
            "subject_type":    "entity",
            "subject_id":      issuer_norm,
            "entity_name":     str(row.get("issuer_name", "")),
            "signal_value":    par,
            "threshold":       0.0,
            "confidence":      0.85,
            "evidence_source": "pr_emma_bonds;pr_all_awards_master",
            "evidence_row_ids": f"emma:{row.get('cusip','')};awards:{';'.join(award_names[issuer_norm][:5])}",
            "explanation":     (
                f"{row.get('issuer_name','')} is both a municipal bond issuer "
                f"(CUSIP {row.get('cusip','')}, ${par:,.0f} par) "
                f"and a PR contract/grant recipient"
            ),
        })
    return signals


def _signals_geographic_clustering(awards: pd.DataFrame) -> list[dict]:
    signals: list[dict] = []
    if awards.empty:
        return signals

    col = None
    for candidate in ("pop_county", "municipality", "place_of_performance_city"):
        if candidate in awards.columns:
            col = candidate
            break
    if col is None:
        return signals

    counts = awards[col].replace("", pd.NA).dropna().value_counts()
    total = len(awards)
    if total == 0:
        return signals

    for seq, (place, count) in enumerate(counts.items()):
        pct = count / total
        if pct < GEO_CLUSTER_THRESHOLD:
            continue
        top_rows = awards[awards[col] == place]
        top_recipients = top_rows.get(
            "recipient_name_normalized",
            top_rows.get("recipient_name", pd.Series(dtype=str))
        ).value_counts().head(3).index.tolist()
        signals.append({
            "signal_id":       _signal_id("geographic_clustering", str(place), seq),
            "signal_family":   "geographic_clustering",
            "signal_type":     "municipality_award_concentration",
            "severity":        "medium",
            "subject_type":    "municipality",
            "subject_id":      str(place),
            "entity_name":     str(place),
            "signal_value":    round(pct, 6),
            "threshold":       GEO_CLUSTER_THRESHOLD,
            "confidence":      0.80,
            "evidence_source": "pr_all_awards_master",
            "evidence_row_ids": ";".join(top_rows.get("award_id", pd.Series(dtype=str)).tolist()[:10]),
            "explanation":     (
                f"{place} accounts for {pct:.1%} of PR awards ({count}/{total}); "
                f"top recipients: {', '.join(top_recipients[:2])}"
            ),
        })
    return signals


def _signals_stale_lineage(awards: pd.DataFrame) -> list[dict]:
    signals: list[dict] = []
    if awards.empty:
        return signals

    for seq, (_, row) in enumerate(awards.iterrows()):
        missing = [
            f for f in LINEAGE_REQUIRED_FIELDS
            if not str(row.get(f, "")).strip()
        ]
        if not missing:
            continue
        signals.append({
            "signal_id":       _signal_id("stale_lineage", str(row.get("award_id", seq)), seq),
            "signal_family":   "stale_lineage",
            "signal_type":     "missing_lineage_fields",
            "severity":        "low",
            "subject_type":    "award",
            "subject_id":      str(row.get("award_id", "")),
            "entity_name":     str(row.get("recipient_name_normalized", row.get("recipient_name", ""))),
            "signal_value":    float(len(missing)),
            "threshold":       0.0,
            "confidence":      0.70,
            "evidence_source": "pr_all_awards_master",
            "evidence_row_ids": str(row.get("award_id", "")),
            "explanation":     (
                f"Award {row.get('award_id','')} missing lineage fields: "
                f"{', '.join(missing)}"
            ),
        })
    return signals


# ---------- Score aggregation ----------

_FAMILY_WEIGHT: dict[str, float] = {
    "concentration":       1.0,
    "repeat_awards":       0.7,
    "subaward_opacity":    0.8,
    "parent_sub_mismatch": 1.0,
    "political_overlap":   0.6,
    "bond_contract_overlap": 0.5,
    "geographic_clustering": 0.4,
    "stale_lineage":       0.3,
}

_SEVERITY_WEIGHT: dict[str, float] = {"high": 1.0, "medium": 0.6, "low": 0.3}


def _compute_entity_scores(signals: list[dict]) -> list[dict]:
    """Roll up signals into per-entity risk scores (0–1 range)."""
    entity_signals: dict[str, list[dict]] = {}
    for s in signals:
        if s["subject_type"] in ("entity", "chain"):
            key = s.get("subject_id") or s.get("entity_name", "unknown")
            entity_signals.setdefault(key, []).append(s)

    scores = []
    for entity_id, sigs in entity_signals.items():
        families = {s["signal_family"] for s in sigs}
        total_weight = sum(
            _FAMILY_WEIGHT.get(s["signal_family"], 0.5)
            * _SEVERITY_WEIGHT.get(s["severity"], 0.5)
            * s.get("confidence", 0.5)
            for s in sigs
        )
        max_possible = len(_FAMILY_WEIGHT) * 1.0
        risk_score = min(1.0, round(total_weight / max_possible, 4))
        dominant = max(families, key=lambda f: _FAMILY_WEIGHT.get(f, 0))
        entity_name = sigs[0].get("entity_name", entity_id)
        scores.append({
            "entity_id":             entity_id,
            "entity_name":           entity_name,
            "risk_score":            risk_score,
            "signal_count":          len(sigs),
            "signal_families":       ";".join(sorted(families)),
            "dominant_signal_family": dominant,
            "confidence":            round(sum(s.get("confidence", 0) for s in sigs) / len(sigs), 4),
            "generated_at":          _now_iso(),
        })
    return sorted(scores, key=lambda x: x["risk_score"], reverse=True)


def _compute_project_scores(signals: list[dict], chains: pd.DataFrame) -> list[dict]:
    """Per-chain/project risk scores."""
    chain_signals: dict[str, list[dict]] = {}
    for s in signals:
        if s["subject_type"] == "chain":
            chain_signals.setdefault(s["subject_id"], []).append(s)

    scores = []
    chain_rows = chains.to_dict("records") if not chains.empty else []
    for row in chain_rows:
        cid = str(row.get("chain_id", ""))
        sigs = chain_signals.get(cid, [])
        total_weight = sum(
            _FAMILY_WEIGHT.get(s["signal_family"], 0.5) * _SEVERITY_WEIGHT.get(s["severity"], 0.5)
            for s in sigs
        )
        max_possible = 3.0
        scores.append({
            "project_id":     str(row.get("project_id", cid)),
            "chain_id":       cid,
            "award_id":       str(row.get("award_id", "")),
            "prime_name":     str(row.get("prime_name", "")),
            "sub_name":       str(row.get("sub_name", "")),
            "municipality":   str(row.get("municipality", "")),
            "obligation_amount": str(row.get("obligation_amount", "")),
            "risk_score":     min(1.0, round(total_weight / max_possible, 4)),
            "signal_count":   len(sigs),
            "chain_confidence": str(row.get("link_confidence", "")),
            "opacity_flag":   any(s["signal_family"] == "subaward_opacity" for s in sigs),
            "generated_at":   _now_iso(),
        })
    return sorted(scores, key=lambda x: x["risk_score"], reverse=True)


def _compute_municipality_scores(signals: list[dict], awards: pd.DataFrame) -> list[dict]:
    """Per-municipality risk scores."""
    muni_signals: dict[str, list[dict]] = {}
    for s in signals:
        if s["subject_type"] == "municipality":
            muni_signals.setdefault(s["subject_id"], []).append(s)

    muni_award_stats: dict[str, dict] = {}
    if not awards.empty:
        col = None
        for c in ("pop_county", "municipality"):
            if c in awards.columns:
                col = c
                break
        if col:
            for place, grp in awards.groupby(col):
                if not str(place).strip():
                    continue
                amounts = grp.get("obligated_amount", pd.Series(dtype=str)).apply(_to_float)
                top_r_col = "recipient_name_normalized" if "recipient_name_normalized" in grp.columns else "recipient_name"
                top_r = grp[top_r_col].value_counts().index[0] if len(grp) else ""
                muni_award_stats[str(place)] = {
                    "award_count": len(grp),
                    "total_amount": amounts.sum(),
                    "top_recipient": top_r,
                }

    all_munis = set(muni_signals.keys()) | set(muni_award_stats.keys())
    scores = []
    for muni in all_munis:
        sigs = muni_signals.get(muni, [])
        stats = muni_award_stats.get(muni, {})
        total_weight = sum(
            _FAMILY_WEIGHT.get(s["signal_family"], 0.5) * _SEVERITY_WEIGHT.get(s["severity"], 0.5)
            for s in sigs
        )
        scores.append({
            "municipality":     muni,
            "award_count":      stats.get("award_count", 0),
            "total_amount":     round(stats.get("total_amount", 0.0), 2),
            "top_recipient":    stats.get("top_recipient", ""),
            "risk_score":       min(1.0, round(total_weight / 2.0, 4)),
            "signal_count":     len(sigs),
            "generated_at":     _now_iso(),
        })
    return sorted(scores, key=lambda x: x["risk_score"], reverse=True)


# ---------- Public API ----------

SIGNAL_COLUMNS = [
    "signal_id", "signal_family", "signal_type", "severity",
    "subject_type", "subject_id", "entity_name",
    "signal_value", "threshold", "confidence",
    "evidence_source", "evidence_row_ids", "explanation",
    "generated_at",
]

ENTITY_SCORE_COLUMNS = [
    "entity_id", "entity_name", "risk_score", "signal_count",
    "signal_families", "dominant_signal_family", "confidence", "generated_at",
]

PROJECT_SCORE_COLUMNS = [
    "project_id", "chain_id", "award_id", "prime_name", "sub_name",
    "municipality", "obligation_amount", "risk_score", "signal_count",
    "chain_confidence", "opacity_flag", "generated_at",
]

MUNICIPALITY_SCORE_COLUMNS = [
    "municipality", "award_count", "total_amount", "top_recipient",
    "risk_score", "signal_count", "generated_at",
]


def compute_signals(root: Path | None = None) -> dict[str, Any]:
    """Compute all risk signals from R5 data shapes.

    Returns a dict with keys: signals, entity_scores, project_scores,
    municipality_scores, metadata.
    """
    root = root or REPO_ROOT

    def _path(p: Path) -> Path:
        return root / p.relative_to(REPO_ROOT) if p.is_absolute() else root / p

    awards     = _read_csv(_path(AWARDS_PATH))
    chains     = _read_csv(_path(CHAINS_PATH))
    entities   = _read_csv(_path(ENTITIES_PATH))
    emma       = _read_csv(_path(EMMA_PATH))
    lda        = _read_csv(_path(LDA_PATH))
    fec        = _read_csv(_path(FEC_PATH))
    cabilderos = _read_csv(_path(CABILDEROS_PATH))

    ts = _now_iso()

    all_signals: list[dict] = []
    all_signals.extend(_signals_concentration(awards))
    all_signals.extend(_signals_repeat_awards(awards))
    all_signals.extend(_signals_subaward_opacity(chains))
    all_signals.extend(_signals_parent_sub_mismatch(chains))
    all_signals.extend(_signals_political_overlap(awards, lda, fec, cabilderos))
    all_signals.extend(_signals_bond_contract_overlap(awards, emma))
    all_signals.extend(_signals_geographic_clustering(awards))
    all_signals.extend(_signals_stale_lineage(awards))

    # Stamp generated_at on all signals
    for s in all_signals:
        s.setdefault("generated_at", ts)
        # Ensure all SIGNAL_COLUMNS present
        for col in SIGNAL_COLUMNS:
            s.setdefault(col, "")

    entity_scores      = _compute_entity_scores(all_signals)
    project_scores     = _compute_project_scores(all_signals, chains)
    municipality_scores = _compute_municipality_scores(all_signals, awards)

    metadata = {
        "schema_version":       SCHEMA_VERSION,
        "generated_at":         ts,
        "signal_count":         len(all_signals),
        "entity_count":         len(entity_scores),
        "project_count":        len(project_scores),
        "municipality_count":   len(municipality_scores),
        "input_rows": {
            "awards":     len(awards),
            "chains":     len(chains),
            "entities":   len(entities),
            "emma":       len(emma),
            "lda":        len(lda),
            "fec":        len(fec),
            "cabilderos": len(cabilderos),
        },
        "thresholds": {
            "concentration":       CONCENTRATION_THRESHOLD,
            "repeat_award":        REPEAT_AWARD_THRESHOLD,
            "opacity_confidence":  OPACITY_CONFIDENCE_MIN,
            "geo_cluster":         GEO_CLUSTER_THRESHOLD,
        },
        "families_fired": sorted({s["signal_family"] for s in all_signals}),
    }

    return {
        "signals":             all_signals,
        "entity_scores":       entity_scores,
        "project_scores":      project_scores,
        "municipality_scores": municipality_scores,
        "metadata":            metadata,
    }
