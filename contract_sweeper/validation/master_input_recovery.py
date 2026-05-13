"""R4 master input recovery and fail-closed rebuild orchestration.

Goals:
- Resolve build_unified_master expected inputs from real source/staging/normalized files.
- Forbid stale report/summary/top-node/graph artifacts as build inputs.
- Enforce fail-closed behavior when required inputs are unresolved.
- Rebuild pr_all_awards_master only when recovery gates pass.
"""

from __future__ import annotations

import ast
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


FORBIDDEN_PATH_TOKENS = (
    "report",
    "summary",
    "top_nodes",
    "network.graphml",
    "network_summary",
    "dominance",
    "power_network",
    "prime_sub",
)

ALLOWED_ROOT_PREFIXES = (
    "data/staging/processed",
    "data/staging/normalized",
    "data/staging/raw",
    "data/staging/expansion",
    "data/normalized",
    "data/raw",
)

AWARD_SIGNAL_COLUMNS = {
    "award_id",
    "contract_id",
    "recipient_name",
    "vendor_name",
    "obligated_amount",
    "total_obligation",
    "award_date",
    "fiscal_year",
    "source_dataset",
}


@dataclass(frozen=True)
class BuilderInputSpec:
    expected_relpath: str
    dataset_label: str
    input_group: str


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


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _row_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                return max(sum(1 for _ in handle) - 1, 0)
        if suffix == ".parquet":
            return len(pd.read_parquet(path))
    except Exception:
        return 0
    return 0


def _csv_columns(path: Path) -> set[str]:
    if not path.exists() or path.suffix.lower() != ".csv":
        return set()
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            return {str(c).strip().lower() for c in (reader.fieldnames or []) if c}
    except Exception:
        return set()


def _looks_like_award_table(path: Path) -> bool:
    cols = _csv_columns(path)
    if not cols:
        return False
    overlap = len(cols.intersection(AWARD_SIGNAL_COLUMNS))
    return overlap >= 2


def _relpath(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _is_forbidden_relpath(relpath: str) -> bool:
    lowered = relpath.lower()
    return any(token in lowered for token in FORBIDDEN_PATH_TOKENS)


def _is_allowed_relpath(relpath: str) -> bool:
    normalized = relpath.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in ALLOWED_ROOT_PREFIXES)


def _manifest_exists(path: Path) -> bool:
    candidates = (
        path.with_suffix(path.suffix + ".manifest.json"),
        path.parent / "manifest.json",
        path.parent / "_manifest.json",
    )
    return any(p.exists() for p in candidates)


def _parse_builder_lists(build_script: Path) -> tuple[list[tuple[str, str]], list[str]]:
    if not build_script.exists():
        return [], []

    text = build_script.read_text(encoding="utf-8", errors="replace")
    module = ast.parse(text)
    new_masters: list[tuple[str, str]] = []
    expansion: list[str] = []

    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "NEW_MASTERS":
                try:
                    value = ast.literal_eval(node.value)
                    new_masters = [(str(v[0]), str(v[1])) for v in value]
                except Exception:
                    new_masters = []
            if isinstance(target, ast.Name) and target.id == "EXPANSION_FILES":
                try:
                    value = ast.literal_eval(node.value)
                    expansion = [str(v) for v in value]
                except Exception:
                    expansion = []
    return new_masters, expansion


def expected_builder_inputs(root: Path) -> list[BuilderInputSpec]:
    build_script = Path(root) / "scripts" / "build_unified_master.py"
    new_masters, expansion = _parse_builder_lists(build_script)

    out: list[BuilderInputSpec] = [
        BuilderInputSpec(
            expected_relpath="data/staging/processed/pr_contracts_master.csv",
            dataset_label="contracts",
            input_group="core",
        )
    ]
    out.extend(
        BuilderInputSpec(
            expected_relpath=f"data/staging/processed/{filename}",
            dataset_label=dataset,
            input_group="canonical_master",
        )
        for filename, dataset in new_masters
    )
    out.extend(
        BuilderInputSpec(
            expected_relpath=f"data/staging/expansion/{filename}",
            dataset_label="contracts",
            input_group="expansion",
        )
        for filename in expansion
    )
    return out


def _token_score(expected_name: str, candidate_name: str) -> int:
    exp_stem = Path(expected_name).stem.lower()
    cand_stem = Path(candidate_name).stem.lower()
    score = 0
    if exp_stem == cand_stem:
        score += 20
    if expected_name.lower() == candidate_name.lower():
        score += 25

    tokens = [t for t in exp_stem.replace("-", "_").split("_") if t and t not in {"pr", "master", "csv"}]
    for token in tokens:
        if token in cand_stem:
            score += 3
    return score


def _fallback_candidates(root: Path, spec: BuilderInputSpec) -> tuple[list[Path], list[Path]]:
    expected_name = Path(spec.expected_relpath).name
    search_roots = [Path(root) / prefix for prefix in ALLOWED_ROOT_PREFIXES]

    allowed: list[Path] = []
    forbidden: list[Path] = []

    for base in search_roots:
        if not base.exists():
            continue
        for cand in base.rglob("*"):
            if not cand.is_file() or cand.suffix.lower() not in {".csv", ".parquet"}:
                continue
            rel = _relpath(Path(root), cand)
            if not _is_allowed_relpath(rel):
                continue
            if _is_forbidden_relpath(rel):
                forbidden.append(cand)
                continue

            score = _token_score(expected_name, cand.name)
            if score <= 0:
                continue
            if cand.suffix.lower() == ".csv" and not _looks_like_award_table(cand):
                continue
            allowed.append(cand)

    # Prefer higher score, then larger files.
    allowed = sorted(
        set(allowed),
        key=lambda p: (_token_score(expected_name, p.name), _row_count(p)),
        reverse=True,
    )
    forbidden = sorted(set(forbidden), key=lambda p: p.as_posix())
    return allowed, forbidden


def resolve_builder_input_map(root: Path) -> dict[str, Any]:
    root = Path(root)
    specs = expected_builder_inputs(root)

    audit_rows: list[dict[str, Any]] = []
    mapping: dict[str, dict[str, str]] = {}
    missing_expected: list[str] = []
    forbidden_candidates: list[str] = []

    for spec in specs:
        expected_path = root / spec.expected_relpath
        mapping_mode = ""
        mapped_path: Path | None = None
        notes = ""

        if expected_path.exists():
            rel = _relpath(root, expected_path)
            if _is_forbidden_relpath(rel):
                notes = "expected path exists but is forbidden by stale/report guard"
                missing_expected.append(spec.expected_relpath)
            else:
                mapped_path = expected_path
                mapping_mode = "exact"
        else:
            candidates, forbidden = _fallback_candidates(root, spec)
            forbidden_candidates.extend(_relpath(root, p) for p in forbidden)
            if candidates:
                mapped_path = candidates[0]
                mapping_mode = "fallback"
                notes = f"mapped from {len(candidates)} candidate(s)"
            else:
                missing_expected.append(spec.expected_relpath)
                notes = "no valid fallback candidates"

        if mapped_path is not None:
            mapped_rel = _relpath(root, mapped_path)
            mapping[spec.expected_relpath] = {
                "mapped_rel": mapped_rel,
                "mapping_mode": mapping_mode,
                "dataset_label": spec.dataset_label,
                "input_group": spec.input_group,
            }

        mapped_rel = mapping.get(spec.expected_relpath, {}).get("mapped_rel", "")
        mapped_abs = root / mapped_rel if mapped_rel else None
        rows = _row_count(mapped_abs) if mapped_abs and mapped_abs.exists() else 0

        audit_rows.append(
            {
                "expected_input": spec.expected_relpath,
                "input_group": spec.input_group,
                "dataset_label": spec.dataset_label,
                "mapping_mode": mapping_mode or "missing",
                "mapped_input": mapped_rel,
                "mapped_exists": bool(mapped_abs and mapped_abs.exists()),
                "row_count": rows,
                "manifest_exists": _manifest_exists(mapped_abs) if mapped_abs and mapped_abs.exists() else False,
                "forbidden_candidate_count": len([p for p in forbidden_candidates if Path(p).name == Path(spec.expected_relpath).name]),
                "notes": notes,
            }
        )

    return {
        "expected_input_count": len(specs),
        "mapped_input_count": len(mapping),
        "missing_input_count": len(missing_expected),
        "forbidden_candidate_count": len(set(forbidden_candidates)),
        "missing_expected_inputs": sorted(set(missing_expected)),
        "forbidden_candidates": sorted(set(forbidden_candidates)),
        "input_map": mapping,
        "audit_rows": audit_rows,
    }


def run_recovery_and_rebuild(root: Path, *, allow_partial_rebuild: bool = False) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    prior_rebuild = _read_json(exports_dir / "rebuild_status.json")
    resolved = resolve_builder_input_map(root)

    # Build should fail closed unless explicitly overridden.
    build_result: dict[str, Any] = {}
    build_error = ""
    rebuild_attempted = False
    rebuild_succeeded = False

    missing = resolved["missing_input_count"]
    forbidden = resolved["forbidden_candidate_count"]

    can_attempt_rebuild = bool(allow_partial_rebuild or (missing == 0 and forbidden == 0))
    dedup_trace_rows: list[dict[str, Any]] = []
    source_contribution_rows: list[dict[str, Any]] = []
    rebuilt_outputs: dict[str, str] = {}
    schema_validation_passed = False

    if can_attempt_rebuild:
        rebuild_attempted = True
        try:
            from scripts.build_unified_master import run as run_unified

            build_result = run_unified(
                root=root,
                input_map=resolved["input_map"],
                require_all_inputs=(not allow_partial_rebuild),
                fail_on_forbidden=True,
            )
            # R4.9 artifact upgrades: export parquet + source matrix + dedup trace.
            master_csv = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
            master_parquet = root / "data" / "staging" / "processed" / "contracts_master.parquet"
            if not master_csv.exists():
                raise RuntimeError("Unified master CSV missing after rebuild")

            master_df = pd.read_csv(master_csv, dtype=str, low_memory=False)
            required_cols = {
                "award_id",
                "source_dataset",
                "source_record_id",
                "source_lineage_path",
                "source_lineage_mode",
            }
            missing_required = sorted(required_cols.difference(master_df.columns))
            if missing_required:
                raise RuntimeError(f"Schema violation in rebuilt master: missing columns {missing_required}")
            schema_validation_passed = True

            master_df.to_parquet(master_parquet, index=False)
            rebuilt_outputs["pr_all_awards_master_csv"] = "data/staging/processed/pr_all_awards_master.csv"
            rebuilt_outputs["contracts_master_parquet"] = "data/staging/processed/contracts_master.parquet"

            if "source_dataset" in master_df.columns:
                for ds, grp in master_df.groupby("source_dataset", dropna=False):
                    source_contribution_rows.append(
                        {
                            "source_dataset": str(ds),
                            "row_count": int(len(grp)),
                            "unique_award_id_count": int(grp.get("award_id", pd.Series(dtype=str)).fillna("").replace("", pd.NA).dropna().nunique()),
                        }
                    )
            if "award_id" in master_df.columns and "source_dataset" in master_df.columns:
                dup_mask = master_df["award_id"].fillna("").str.strip() != ""
                dup_df = master_df.loc[dup_mask].copy()
                grouped = dup_df.groupby("award_id")["source_dataset"].nunique()
                duplicate_ids = grouped[grouped > 1]
                for award_id, unique_sources in duplicate_ids.items():
                    dedup_trace_rows.append(
                        {
                            "award_id": str(award_id),
                            "source_dataset_count": int(unique_sources),
                            "source_datasets": "|".join(sorted(dup_df.loc[dup_df["award_id"] == award_id, "source_dataset"].astype(str).unique())),
                        }
                    )
            rebuild_succeeded = True
        except Exception as exc:
            build_error = str(exc)
            rebuild_succeeded = False
    else:
        build_error = "Fail-closed: unresolved master inputs or forbidden candidates detected"

    summary_path = root / "data" / "staging" / "processed" / "pr_all_awards_summary.json"
    summary = _read_json(summary_path)

    observed_summary_entities = _safe_int(summary.get("unique_recipients"))
    observed_summary_rows = _safe_int(summary.get("total_rows"))
    rebuild_rows = observed_summary_rows if rebuild_succeeded else 0
    rebuild_unique_entities = observed_summary_entities if rebuild_succeeded else 0

    # R4 gate: all inputs resolved, no forbidden candidates, rebuild succeeded, and rows populated.
    r4_gate_passed = bool(
        missing == 0
        and forbidden == 0
        and rebuild_succeeded
        and rebuild_rows > 0
        and rebuild_unique_entities > 0
    )

    # Keep Phase 7/8 blocked until R4+R5+R6 all pass.
    r5_passed = bool(prior_rebuild.get("r5_gate_passed", False))
    r6_passed = bool(prior_rebuild.get("r6_gate_passed", False))
    phase_7_8_blocked = bool((not r4_gate_passed) or (not r5_passed) or (not r6_passed))

    block_reasons: list[str] = []
    if not r4_gate_passed:
        block_reasons.append("R4 gate failed")
    if not r5_passed:
        block_reasons.append("R5 gate not passed")
    if not r6_passed:
        block_reasons.append("R6 gate not passed")

    recovery_payload = {
        "generated_at": _utc_now(),
        "expected_input_count": resolved["expected_input_count"],
        "mapped_input_count": resolved["mapped_input_count"],
        "missing_input_count": resolved["missing_input_count"],
        "forbidden_candidate_count": resolved["forbidden_candidate_count"],
        "missing_expected_inputs": resolved["missing_expected_inputs"],
        "forbidden_candidates": resolved["forbidden_candidates"],
        "allow_partial_rebuild": allow_partial_rebuild,
        "rebuild_attempted": rebuild_attempted,
        "rebuild_succeeded": rebuild_succeeded,
        "build_error": build_error,
        "rebuild_rows": rebuild_rows,
        "rebuild_unique_entities": rebuild_unique_entities,
        "observed_summary_rows": observed_summary_rows,
        "observed_summary_unique_entities": observed_summary_entities,
        "r4_gate_passed": r4_gate_passed,
        "phase_7_8_blocked": phase_7_8_blocked,
        "phase_7_8_block_reason": "; ".join(block_reasons) if block_reasons else "R4+R5+R6 gates passed",
        "r4_outputs": {
            "master_input_recovery_audit": "data/exports/master_input_recovery_audit.csv",
            "master_input_recovery_status": "data/exports/master_input_recovery_audit.json",
            "master_input_blockers": "data/review_queue/master_input_recovery_blockers.csv",
            "rebuild_audit": "data/exports/r49_rebuild_audit.json",
            "source_contribution_matrix": "data/exports/r49_source_contribution_matrix.csv",
            "deduplication_trace": "data/exports/r49_deduplication_trace.csv",
        },
        "forbidden_artifact_usage": False,
        "schema_validation_passed": schema_validation_passed,
        "rebuild_outputs": rebuilt_outputs,
    }

    _write_csv(
        exports_dir / "master_input_recovery_audit.csv",
        resolved["audit_rows"],
        [
            "expected_input",
            "input_group",
            "dataset_label",
            "mapping_mode",
            "mapped_input",
            "mapped_exists",
            "row_count",
            "manifest_exists",
            "forbidden_candidate_count",
            "notes",
        ],
    )

    blockers = [
        {
            "blocker": "missing_master_inputs",
            "count": resolved["missing_input_count"],
            "details": "|".join(resolved["missing_expected_inputs"]),
        },
        {
            "blocker": "forbidden_candidates_detected",
            "count": resolved["forbidden_candidate_count"],
            "details": "|".join(resolved["forbidden_candidates"]),
        },
        {
            "blocker": "rebuild_failed",
            "count": 0 if rebuild_succeeded else 1,
            "details": build_error,
        },
    ]
    _write_csv(
        review_dir / "master_input_recovery_blockers.csv",
        blockers,
        ["blocker", "count", "details"],
    )

    _write_json(exports_dir / "master_input_recovery_audit.json", recovery_payload)
    _write_csv(
        exports_dir / "r49_source_contribution_matrix.csv",
        source_contribution_rows,
        ["source_dataset", "row_count", "unique_award_id_count"],
    )
    _write_csv(
        exports_dir / "r49_deduplication_trace.csv",
        dedup_trace_rows,
        ["award_id", "source_dataset_count", "source_datasets"],
    )
    _write_json(
        exports_dir / "r49_rebuild_audit.json",
        {
            "generated_at": recovery_payload["generated_at"],
            "rebuild_attempted": rebuild_attempted,
            "rebuild_succeeded": rebuild_succeeded,
            "build_error": build_error,
            "schema_validation_passed": schema_validation_passed,
            "forbidden_artifact_usage": False,
            "rebuild_outputs": rebuilt_outputs,
            "source_contribution_rows": len(source_contribution_rows),
            "deduplication_trace_rows": len(dedup_trace_rows),
        },
    )

    # Persist R4 in shared rebuild status.
    rebuild_status = dict(prior_rebuild)
    rebuild_status.update(
        {
            "r4_generated_at": recovery_payload["generated_at"],
            "r4_gate_passed": r4_gate_passed,
            "r4_missing_input_count": resolved["missing_input_count"],
            "r4_forbidden_candidate_count": resolved["forbidden_candidate_count"],
            "r4_rebuild_rows": rebuild_rows,
            "r4_rebuild_unique_entities": rebuild_unique_entities,
            "r4_observed_summary_rows": observed_summary_rows,
            "r4_observed_summary_unique_entities": observed_summary_entities,
            "phase_7_8_blocked": phase_7_8_blocked,
            "phase_7_8_block_reason": recovery_payload["phase_7_8_block_reason"],
            "r4_primary_collapse_cause": (
                "build_unified_master_input_gap_with_stale_summary_replay"
                if resolved["missing_input_count"] > 0
                else "r4_cause_not_detected"
            ),
            "r4_outputs": recovery_payload["r4_outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return recovery_payload
