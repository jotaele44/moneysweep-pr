"""R4.5 source-input recovery and canonical staging.

Purpose:
- Recover real source files for build_unified_master required inputs.
- Restrict recovery to raw/staging/normalized/exports/runtime roots.
- Reject report/summary/graph/top-node artifacts as recovery inputs.
- Materialize canonical staging files with source lineage when recoverable.
- Emit a manual download queue when recovery is not possible.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from contract_sweeper.validation.master_input_recovery import expected_builder_inputs
from scripts.build_unified_master import _normalize_name


ALLOWED_RECOVERY_ROOTS = (
    "data/raw",
    "data/staging/raw",
    "data/staging/normalized",
    "data/staging/processed",
    "data/staging/expansion",
    "data/normalized",
    "data/exports",
    "contract_sweeper/runtime",
)

REJECT_ARTIFACT_TOKENS = (
    "report",
    "summary",
    "graph",
    "network",
    "top_node",
    "top_nodes",
    "dominance",
    "power_network",
    "prime_sub",
    "investigative",
)

CANDIDATE_SUFFIXES = {".csv", ".parquet", ".xlsx", ".xls", ".json"}

AWARD_SIGNAL_COLUMNS = {
    "award_id",
    "contract_id",
    "recipient_name",
    "vendor_name",
    "awarding_agency",
    "agency_name",
    "obligated_amount",
    "total_obligation",
    "award_date",
    "fiscal_year",
    "source_dataset",
}

CANONICAL_COLUMNS = [
    "award_id",
    "recipient_name",
    "recipient_name_normalized",
    "recipient_uei",
    "awarding_agency",
    "awarding_sub_agency",
    "obligated_amount",
    "award_date",
    "fiscal_year",
    "pop_state",
    "pop_county",
    "description",
    "source_file",
    "source_dataset",
    "award_category",
    "source_system",
    "source_record_id",
    "source_lineage_path",
    "source_lineage_mode",
]

LEGACY_CONTRACT_COLUMNS = [
    "contract_id",
    "vendor_name",
    "agency_name",
    "award_date",
    "obligated_amount",
    "pop_state",
    "source_file",
    "fiscal_year",
    "source_system",
    "source_record_id",
    "source_lineage_path",
    "source_lineage_mode",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _relpath(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _is_rejected_artifact(relpath: str) -> bool:
    lowered = relpath.lower()
    return any(token in lowered for token in REJECT_ARTIFACT_TOKENS)


def _read_tabular(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False)
    if suffix == ".parquet":
        return pd.read_parquet(path).astype(str)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return pd.DataFrame(payload).astype(str)
        if isinstance(payload, dict):
            return pd.DataFrame([payload]).astype(str)
    return pd.DataFrame()


def _column_lookup(df: pd.DataFrame) -> dict[str, str]:
    return {str(c).strip().lower(): str(c) for c in df.columns}


def _series_from_candidates(df: pd.DataFrame, candidates: tuple[str, ...]) -> pd.Series:
    lookup = _column_lookup(df)
    for cand in candidates:
        key = cand.strip().lower()
        if key in lookup:
            return df[lookup[key]].fillna("").astype(str)
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _looks_like_award_table(df: pd.DataFrame) -> bool:
    if df.empty:
        return False
    overlap = len({str(c).strip().lower() for c in df.columns}.intersection(AWARD_SIGNAL_COLUMNS))
    return overlap >= 2


def _token_score(expected_name: str, dataset_label: str, candidate: Path) -> int:
    exp_stem = Path(expected_name).stem.lower()
    cand_stem = candidate.stem.lower()
    score = 0
    if exp_stem == cand_stem:
        score += 30
    tokens = [t for t in exp_stem.replace("-", "_").split("_") if t and t not in {"pr", "master", "csv"}]
    for token in tokens:
        if token in cand_stem:
            score += 4
    if dataset_label and dataset_label.lower() in cand_stem:
        score += 6
    if "contracts" in exp_stem and "contract" in cand_stem:
        score += 4
    return score


def _award_category(dataset_label: str) -> str:
    contracts_like = {"contracts", "subawards", "dot", "usace_civil"}
    return "contract" if dataset_label in contracts_like else "assistance"


def _apply_lineage(df: pd.DataFrame, source_system: str, source_relpath: str, mode: str, id_col: str) -> pd.DataFrame:
    row_ids = pd.Series(range(1, len(df) + 1), index=df.index).astype(str)
    base_ids = df[id_col].fillna("").astype(str).str.strip() if id_col in df.columns else pd.Series([""] * len(df), index=df.index)
    resolved_ids = base_ids.where(base_ids != "", "ROW_" + row_ids)
    df["source_system"] = source_system
    df["source_record_id"] = source_system + ":" + resolved_ids
    df["source_lineage_path"] = source_relpath
    df["source_lineage_mode"] = mode
    return df


def _to_canonical(df: pd.DataFrame, dataset_label: str, source_relpath: str) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["award_id"] = _series_from_candidates(df, ("award_id", "contract_id", "id", "generated_internal_id", "Award ID", "PIID"))
    out["recipient_name"] = _series_from_candidates(df, ("recipient_name", "vendor_name", "Recipient Name", "Vendor Name", "company_name"))
    out["recipient_name_normalized"] = out["recipient_name"].apply(_normalize_name)
    out["recipient_uei"] = _series_from_candidates(df, ("recipient_uei", "uei", "sam_uei", "Unique Entity ID (SAM)"))
    out["awarding_agency"] = _series_from_candidates(df, ("awarding_agency", "agency_name", "Awarding Agency", "Awarding Agency Name"))
    out["awarding_sub_agency"] = _series_from_candidates(df, ("awarding_sub_agency", "awarding_subagency", "Awarding Sub Agency"))
    out["obligated_amount"] = _series_from_candidates(df, ("obligated_amount", "total_obligation", "Total Obligation", "Action Obligation"))
    out["award_date"] = _series_from_candidates(df, ("award_date", "action_date", "Start Date", "Award Date", "Date Signed"))
    out["fiscal_year"] = _series_from_candidates(df, ("fiscal_year", "year", "FY", "fiscal year", "award_year"))
    out["pop_state"] = _series_from_candidates(df, ("pop_state", "Place of Performance State Code", "state", "state_code"))
    out["pop_county"] = _series_from_candidates(df, ("pop_county", "Place of Performance City", "county", "municipality"))
    out["description"] = _series_from_candidates(df, ("description", "Description", "Award Description", "Project Description"))
    out["source_file"] = Path(source_relpath).name
    out["source_dataset"] = dataset_label
    out["award_category"] = _award_category(dataset_label)

    out = _apply_lineage(
        out,
        source_system=dataset_label or "recovered_source",
        source_relpath=source_relpath,
        mode="recovered",
        id_col="award_id",
    )

    for col in CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[CANONICAL_COLUMNS]


def _to_legacy_contracts(df: pd.DataFrame, source_relpath: str) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["contract_id"] = _series_from_candidates(df, ("contract_id", "award_id", "Award ID", "PIID", "id"))
    out["vendor_name"] = _series_from_candidates(df, ("vendor_name", "recipient_name", "Vendor Name", "Recipient Name", "company_name"))
    out["agency_name"] = _series_from_candidates(df, ("agency_name", "awarding_agency", "Awarding Agency", "Awarding Agency Name"))
    out["award_date"] = _series_from_candidates(df, ("award_date", "action_date", "Award Date", "Date Signed", "Start Date"))
    out["obligated_amount"] = _series_from_candidates(df, ("obligated_amount", "total_obligation", "Total Obligation", "Action Obligation"))
    out["pop_state"] = _series_from_candidates(df, ("pop_state", "Place of Performance State Code", "state", "state_code"))
    out["source_file"] = Path(source_relpath).name
    out["fiscal_year"] = _series_from_candidates(df, ("fiscal_year", "year", "FY", "fiscal year", "award_year"))

    out = _apply_lineage(
        out,
        source_system="contracts",
        source_relpath=source_relpath,
        mode="recovered",
        id_col="contract_id",
    )

    for col in LEGACY_CONTRACT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[LEGACY_CONTRACT_COLUMNS]


def _load_valid_candidates(root: Path) -> tuple[list[Path], set[str]]:
    valid: list[Path] = []
    rejected: set[str] = set()

    for rel_root in ALLOWED_RECOVERY_ROOTS:
        base = root / rel_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in CANDIDATE_SUFFIXES:
                continue
            rel = _relpath(root, path)
            if _is_rejected_artifact(rel):
                rejected.add(rel)
                continue
            try:
                df = _read_tabular(path)
            except Exception:
                continue
            if _looks_like_award_table(df):
                valid.append(path)

    # Deduplicate path list.
    return sorted(set(valid), key=lambda p: p.as_posix()), rejected


def _find_producer_scripts(root: Path, expected_filename: str) -> list[str]:
    scripts_dir = root / "scripts"
    if not scripts_dir.exists():
        return []
    hits: list[str] = []
    for path in scripts_dir.glob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if expected_filename in text and path.name != "build_unified_master.py":
            hits.append(f"scripts/{path.name}")
    return sorted(set(hits))


def _recommended_source_hint(expected_relpath: str, dataset_label: str) -> str:
    name = Path(expected_relpath).name
    hints = {
        "pr_contracts_master.csv": "Run normalization + dedup pipeline to produce contracts master",
        "pr_subawards_master.csv": "Run FSRS/subawards ingestion pipeline",
        "pr_fema_pa_master.csv": "Run FEMA PA ingestion",
        "pr_fema_hmgp_master.csv": "Run FEMA HMGP ingestion",
        "pr_grants_master.csv": "Run USAspending grants ingestion",
        "pr_sba_loans_master.csv": "Run SBA loans ingestion",
        "pr_cdbg_dr_master.csv": "Run HUD/CDBG-DR ingestion",
        "pr_doe_master.csv": "Run DOE ingestion",
        "pr_dot_master.csv": "Run DOT ingestion",
        "pr_hud_master.csv": "Run HUD ingestion",
        "pr_usda_master.csv": "Run USDA ingestion",
        "pr_sbir_master.csv": "Run SBIR ingestion",
        "pr_epa_master.csv": "Run EPA ingestion",
        "pr_usace_civil_master.csv": "Run USACE ingestion",
        "pr_wioa_grants.csv": "Run WIOA ingestion",
        "expansion_idv_indirect_pr.csv": "Run USASpending expansion extraction (IDV indirect PR)",
        "expansion_dod_upr_2001_2015.csv": "Run USASpending expansion extraction (DoD 2001-2015)",
        "expansion_dod_upr_2016_2025.csv": "Run USASpending expansion extraction (DoD 2016-2025)",
        "expansion_reconstruction_2017_2025.csv": "Run USASpending expansion extraction (reconstruction)",
    }
    return hints.get(name, f"Recover or download source input for dataset '{dataset_label}'")


def run_recovery(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    prior = _read_json(exports_dir / "rebuild_status.json")
    specs = expected_builder_inputs(root)
    candidates, rejected_artifacts = _load_valid_candidates(root)

    audit_rows: list[dict[str, Any]] = []
    manual_rows: list[dict[str, Any]] = []

    recovered_count = 0
    existing_count = 0

    for idx, spec in enumerate(specs, start=1):
        expected_path = root / spec.expected_relpath
        expected_name = expected_path.name

        if expected_path.exists() and expected_path.is_file() and expected_path.suffix.lower() == ".csv":
            # Existing expected input qualifies only when not stale artifact-like and has rows.
            rel_existing = _relpath(root, expected_path)
            if not _is_rejected_artifact(rel_existing):
                try:
                    existing_rows = max(len(pd.read_csv(expected_path, dtype=str, low_memory=False)), 0)
                except Exception:
                    existing_rows = 0
                if existing_rows > 0:
                    existing_count += 1
                    audit_rows.append(
                        {
                            "expected_input": spec.expected_relpath,
                            "dataset_label": spec.dataset_label,
                            "input_group": spec.input_group,
                            "recovery_status": "existing",
                            "recovery_mode": "existing",
                            "recovered_from": rel_existing,
                            "source_rows": existing_rows,
                            "recovered_rows": existing_rows,
                            "manifest_written": bool((expected_path.parent / "manifest.json").exists()),
                            "notes": "existing canonical staging file retained",
                        }
                    )
                    continue

        scored = [
            (cand, _token_score(expected_name, spec.dataset_label, cand))
            for cand in candidates
        ]
        scored = [pair for pair in scored if pair[1] > 0]
        scored.sort(key=lambda pair: (pair[1], pair[0].stat().st_size), reverse=True)

        if not scored:
            manual_rows.append(
                {
                    "priority": idx,
                    "expected_input": spec.expected_relpath,
                    "dataset_label": spec.dataset_label,
                    "input_group": spec.input_group,
                    "reason": "no recoverable source file found in allowed roots",
                    "recommended_action": _recommended_source_hint(spec.expected_relpath, spec.dataset_label),
                    "producer_scripts": "|".join(_find_producer_scripts(root, expected_name)),
                }
            )
            audit_rows.append(
                {
                    "expected_input": spec.expected_relpath,
                    "dataset_label": spec.dataset_label,
                    "input_group": spec.input_group,
                    "recovery_status": "manual_queue",
                    "recovery_mode": "none",
                    "recovered_from": "",
                    "source_rows": 0,
                    "recovered_rows": 0,
                    "manifest_written": False,
                    "notes": "manual download/rebuild required",
                }
            )
            continue

        source_path = scored[0][0]
        source_rel = _relpath(root, source_path)
        source_df = _read_tabular(source_path)

        if expected_name == "pr_contracts_master.csv":
            recovered_df = _to_legacy_contracts(source_df, source_rel)
        else:
            recovered_df = _to_canonical(source_df, spec.dataset_label, source_rel)

        expected_path.parent.mkdir(parents=True, exist_ok=True)
        recovered_df.to_csv(expected_path, index=False, encoding="utf-8")

        manifest_payload = {
            "generated_at": _utc_now(),
            "recovery_mode": "source_input_recovery",
            "expected_input": spec.expected_relpath,
            "source_input": source_rel,
            "source_row_count": int(len(source_df)),
            "recovered_row_count": int(len(recovered_df)),
            "dataset_label": spec.dataset_label,
            "input_group": spec.input_group,
        }
        _write_json(expected_path.with_suffix(expected_path.suffix + ".manifest.json"), manifest_payload)

        recovered_count += 1
        audit_rows.append(
            {
                "expected_input": spec.expected_relpath,
                "dataset_label": spec.dataset_label,
                "input_group": spec.input_group,
                "recovery_status": "recovered",
                "recovery_mode": "mapped_from_allowed_root",
                "recovered_from": source_rel,
                "source_rows": int(len(source_df)),
                "recovered_rows": int(len(recovered_df)),
                "manifest_written": True,
                "notes": "canonical staging recovered with lineage",
            }
        )

    expected_count = len(specs)
    unresolved_count = len(manual_rows)
    r4_5_gate_passed = bool(unresolved_count == 0 and expected_count > 0)

    # Keep Phase 7/8 blocked during R4.5 by design.
    phase_7_8_blocked = True
    phase_7_8_reason = (
        "Phase 7/8 blocked during R4.5 source input recovery and canonical staging; "
        "await R5 and R6 validation gates"
    )

    status = {
        "generated_at": _utc_now(),
        "expected_input_count": expected_count,
        "existing_input_count": existing_count,
        "recovered_input_count": recovered_count,
        "manual_queue_count": unresolved_count,
        "rejected_artifact_candidate_count": len(rejected_artifacts),
        "r4_5_gate_passed": r4_5_gate_passed,
        "phase_7_8_blocked": phase_7_8_blocked,
        "phase_7_8_block_reason": phase_7_8_reason,
        "outputs": {
            "source_input_recovery_audit": "data/exports/source_input_recovery_audit.csv",
            "source_input_recovery_status": "data/exports/source_input_recovery_status.json",
            "manual_source_download_queue": "data/review_queue/manual_source_download_queue.csv",
        },
        "rejected_artifact_candidates": sorted(rejected_artifacts),
    }

    _write_csv(
        exports_dir / "source_input_recovery_audit.csv",
        audit_rows,
        [
            "expected_input",
            "dataset_label",
            "input_group",
            "recovery_status",
            "recovery_mode",
            "recovered_from",
            "source_rows",
            "recovered_rows",
            "manifest_written",
            "notes",
        ],
    )
    _write_csv(
        review_dir / "manual_source_download_queue.csv",
        manual_rows,
        [
            "priority",
            "expected_input",
            "dataset_label",
            "input_group",
            "reason",
            "recommended_action",
            "producer_scripts",
        ],
    )
    _write_json(exports_dir / "source_input_recovery_status.json", status)

    rebuild_status = dict(prior)
    rebuild_status.update(
        {
            "r4_5_generated_at": status["generated_at"],
            "r4_5_gate_passed": r4_5_gate_passed,
            "r4_5_expected_input_count": expected_count,
            "r4_5_existing_input_count": existing_count,
            "r4_5_recovered_input_count": recovered_count,
            "r4_5_manual_queue_count": unresolved_count,
            "r4_5_rejected_artifact_candidate_count": len(rejected_artifacts),
            "phase_7_8_blocked": True,
            "phase_7_8_block_reason": phase_7_8_reason,
            "r4_5_outputs": status["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status
