"""R4.9D external blocker freeze and completion gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moneysweep.pipeline.acquisition_package import (
    read_csv,
    read_json,
    safe_int,
    split_pipe,
    utc_now,
    write_csv,
    write_json,
    write_markdown,
)
from moneysweep.pipeline.completion_gate import (
    BLOCKER_ENDPOINT,
    BLOCKER_MANUAL,
    BLOCKER_PHYSICAL,
    BLOCKER_PRODUCER,
    VALID_BLOCKER_CLASSES,
    classify_blocker,
    evaluate_completion_gate,
    unfreeze_condition,
)

FORBIDDEN_ARTIFACT_TOKENS = (
    "report",
    "summary",
    "graph",
    "network",
    "top_nodes",
    "top_node",
    "power_network",
    "dominance",
    "risk_alert",
    "investigative",
)

DEFAULT_REQUIRED_COLUMNS = (
    "award_id|recipient_name|recipient_name_normalized|recipient_uei|awarding_agency|"
    "awarding_sub_agency|obligated_amount|award_date|fiscal_year|pop_state|pop_county|"
    "description|source_file|source_dataset|award_category|source_system|source_record_id|"
    "source_lineage_path|source_lineage_mode"
)
EXPANSION_REQUIRED_COLUMNS = (
    "Award ID|Recipient Name|Awarding Agency|Awarding Sub Agency|Total Obligation|Start Date|"
    "Place of Performance State Code|Place of Performance City|Description|generated_internal_id"
)

DOWNSTREAM_PHASE_BLOCKERS = [
    ("R4.9_PRODUCTION_MASTER_REBUILD", "R4.9 production rebuild blocked"),
    ("R5_ENTITY_RESOLUTION", "R5 entity resolution blocked"),
    ("R6_EXECUTION_CHAIN_REBUILD", "R6 execution chain rebuild blocked"),
    ("R7_FINANCIAL_INTEGRATION", "R7 financial integration blocked"),
    ("R8_GRAPH_REBUILD", "R8 graph rebuild blocked"),
    ("R9_RISK_ENGINE", "R9 risk engine blocked"),
    ("R10_FINAL_REPORTS", "R10 final reports blocked"),
]


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _build_validation_command(target_output_path: str, required_columns: str) -> str:
    target = str(target_output_path or "").strip()
    cols = ",".join(split_pipe(required_columns))
    return (
        'python -c "import pandas as pd; from pathlib import Path; '
        f"p=Path({target!r}); "
        "assert p.exists(), 'missing output'; "
        "df=pd.read_csv(p,dtype=str,low_memory=False); "
        "assert len(df)>0, 'empty output'; "
        f"req={cols!r}.split(',') if {cols!r} else []; "
        "missing=[c for c in req if c and c not in df.columns]; "
        "assert not missing, f'missing columns: {missing}'; "
        "print('rows',len(df))\""
    )


def _required_columns_for_target(target_output_path: str, fallback: str) -> str:
    target = str(target_output_path or "").strip()
    if str(target).startswith("data/staging/expansion/"):
        return fallback or EXPANSION_REQUIRED_COLUMNS
    return fallback or DEFAULT_REQUIRED_COLUMNS


def _source_delivery_markdown(
    *,
    generated_at: str,
    blockers_frozen: int,
    manual_count: int,
    physical_count: int,
    endpoint_count: int,
    producer_count: int,
    unknown_count: int,
    requirements_relpath: str,
) -> str:
    return (
        "# R4.9D Source Recovery Unfreeze Requirements\n\n"
        f"Generated at: {generated_at}\n\n"
        "Status: External blockers frozen. Generic retries are suppressed until external source delivery/access changes.\n\n"
        "## Blocker Summary\n\n"
        f"- Total blockers frozen: {blockers_frozen}\n"
        f"- manual_file_required: {manual_count}\n"
        f"- physical_validated_file_missing: {physical_count}\n"
        f"- endpoint_delivery_blocked: {endpoint_count}\n"
        f"- producer_delivery_blocked: {producer_count}\n"
        f"- unknown_external_blocker: {unknown_count}\n\n"
        "## Unfreeze Rules\n\n"
        "- No generic retry loops until source files/access materially change.\n"
        "- Unfreeze requires delivery of blocked sources plus schema/hash/row validation.\n"
        "- Downstream phases remain blocked until this queue is materially reduced and validated inputs increase.\n\n"
        "## Required Delivery Queue\n\n"
        f"- Source delivery queue: `{requirements_relpath}`\n"
    )


def run_external_blocker_freeze(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    _ = read_json(exports_dir / "external_source_delivery_status_r4_9c.json")
    _ = read_csv(exports_dir / "external_source_delivery_results_r4_9c.csv")
    _ = read_csv(exports_dir / "delivered_source_validation_report_r4_9c.csv")
    _ = read_csv(exports_dir / "validated_source_manifest_inventory_r4_9c.csv")
    blockers_rows = read_csv(review_dir / "external_source_delivery_blockers_r4_9c.csv")
    manual_rows = read_csv(review_dir / "manual_files_still_required_r4_9c.csv")
    physical_rows = read_csv(review_dir / "physical_validated_files_still_missing_r4_9c.csv")
    retry_order_rows = read_csv(review_dir / "backfill_retry_order_r4_9c.csv")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")

    # Optional fallback map for rich validation commands.
    manual_rows_r48i = read_csv(review_dir / "manual_files_still_required_r4_8i.csv")

    manual_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in manual_rows
        if str(row.get("expected_input", "")).strip()
    }
    manual_r48i_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in manual_rows_r48i
        if str(row.get("expected_input", "")).strip()
    }
    physical_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in physical_rows
        if str(row.get("expected_input", "")).strip()
    }
    retry_by_expected = {
        str(row.get("expected_input", "")).strip(): row
        for row in retry_order_rows
        if str(row.get("expected_input", "")).strip()
    }

    freeze_rows: list[dict[str, Any]] = []
    source_delivery_rows: list[dict[str, Any]] = []
    retry_suppression_rows: list[dict[str, Any]] = []
    downstream_blocker_rows: list[dict[str, Any]] = []

    counts = {
        BLOCKER_MANUAL: 0,
        BLOCKER_PHYSICAL: 0,
        BLOCKER_ENDPOINT: 0,
        BLOCKER_PRODUCER: 0,
        "unknown_external_blocker": 0,
    }

    forbidden_artifact_usage = False
    generated_at = utc_now()

    for blocker in blockers_rows:
        request_id = str(blocker.get("request_id", "")).strip()
        expected_input = str(blocker.get("expected_input", "")).strip()
        source_family = str(blocker.get("source_family", "")).strip()
        target_output_path = str(blocker.get("target_output_path", "")).strip()
        reason_blocked = (
            str(blocker.get("blocker_reason", "")).strip() or "external_source_not_delivered"
        )
        next_action = str(blocker.get("next_action", "")).strip()

        manual_row = manual_by_expected.get(expected_input, {})
        manual_r48i_row = manual_r48i_by_expected.get(expected_input, {})
        # NOTE: physical evidence (physical_validated_files_still_missing_r4_9c.csv)
        # is looked up but not yet merged into the blocker record the way manual_row
        # and retry_row are. This binding is retained — rather than the lookup chain
        # deleted — to preserve the half-wired data flow for a follow-up that
        # incorporates physical evidence into classify_blocker(). Tracked in
        # docs/BUILD_EXECUTION_SEQUENCE.md (Wave M, runtime robustness).
        physical_row = physical_by_expected.get(expected_input, {})  # noqa: F841
        retry_row = retry_by_expected.get(expected_input, {})

        blocker_class = classify_blocker(blocker)
        counts[blocker_class] = counts.get(blocker_class, 0) + 1

        target_dropzone_path = str(manual_row.get("target_dropzone_path", "")).strip()
        accepted_filename_patterns = str(manual_row.get("accepted_filename_patterns", "")).strip()
        required_columns = str(manual_row.get("required_columns", "")).strip()
        required_columns = _required_columns_for_target(target_output_path, required_columns)
        validation_command = str(manual_r48i_row.get("validation_command", "")).strip()
        if not validation_command:
            validation_command = _build_validation_command(target_output_path, required_columns)

        condition = unfreeze_condition(
            blocker_class,
            expected_input=expected_input,
            target_output_path=target_output_path,
            target_dropzone_path=target_dropzone_path,
        )

        for raw_path in (expected_input, target_output_path, target_dropzone_path):
            if _contains_forbidden_token(raw_path):
                forbidden_artifact_usage = True

        freeze_row = {
            "frozen_at": generated_at,
            "request_id": request_id,
            "request_type": str(blocker.get("request_type", "")).strip(),
            "source_family": source_family,
            "expected_input": expected_input,
            "target_output_path": target_output_path,
            "target_dropzone_path": target_dropzone_path,
            "accepted_filename_patterns": accepted_filename_patterns,
            "required_columns": required_columns,
            "validation_command": validation_command,
            "blocker_class": blocker_class,
            "reason_blocked": reason_blocked,
            "next_action": next_action,
            "unfreeze_condition": condition,
            "retry_rank_hint": safe_int(retry_row.get("retry_rank")),
            "retry_reason_hint": str(retry_row.get("reason", "")).strip(),
        }
        freeze_rows.append(freeze_row)

        source_delivery_rows.append(
            {
                "expected_input": expected_input,
                "source_family": source_family,
                "target_output_path": target_output_path,
                "target_dropzone_path": target_dropzone_path,
                "accepted_filename_patterns": accepted_filename_patterns,
                "required_columns": required_columns,
                "validation_command": validation_command,
                "reason_blocked": reason_blocked,
                "unfreeze_condition": condition,
                "blocker_class": blocker_class,
            }
        )

        retry_suppression_rows.append(
            {
                "request_id": request_id,
                "expected_input": expected_input,
                "source_family": source_family,
                "suppression_status": "suppressed",
                "suppression_reason": "external_source_unavailable_or_undelivered",
                "suppression_scope": "block_generic_retry_loop",
                "unsuppress_condition": condition,
                "retry_allowed": False,
            }
        )

    for phase_code, phase_reason in DOWNSTREAM_PHASE_BLOCKERS:
        downstream_blocker_rows.append(
            {
                "phase_code": phase_code,
                "blocked": True,
                "blocker_reason": phase_reason,
                "unfreeze_condition": (
                    "External source delivery blockers are cleared and validated source coverage materially improves."
                ),
                "status": "blocked",
            }
        )

    blockers_total = len(blockers_rows)
    blockers_frozen = len(freeze_rows)
    manual_count = int(counts.get(BLOCKER_MANUAL, 0))
    physical_count = int(counts.get(BLOCKER_PHYSICAL, 0))
    endpoint_count = int(counts.get(BLOCKER_ENDPOINT, 0))
    producer_count = int(counts.get(BLOCKER_PRODUCER, 0))
    unknown_count = int(counts.get("unknown_external_blocker", 0))
    retry_suppressed = len(retry_suppression_rows)
    downstream_blocked = len(downstream_blocker_rows)

    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0
    production_status = "NON_PRODUCTION_DIAGNOSTIC"
    row_fabrication_policy = str(
        rebuild_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", True))

    all_classified = all(
        str(row.get("blocker_class", "")).strip() in VALID_BLOCKER_CLASSES for row in freeze_rows
    )
    all_have_unfreeze = all(
        bool(str(row.get("unfreeze_condition", "")).strip()) for row in freeze_rows
    )

    gate_passed = evaluate_completion_gate(
        blockers_total=blockers_total,
        blockers_frozen=blockers_frozen,
        all_classified=all_classified,
        all_have_unfreeze_condition=all_have_unfreeze,
        retry_suppression_count=retry_suppressed,
        downstream_blockers_count=downstream_blocked,
        downloads_executed=downloads_executed,
        rows_ingested=rows_ingested,
        production_inputs_staged=production_inputs_staged,
        forbidden_artifact_usage=forbidden_artifact_usage,
        production_status=production_status,
        row_fabrication_policy=row_fabrication_policy,
        phase_7_8_blocked=phase_7_8_blocked,
    )

    requirements_md_relpath = "data/exports/source_recovery_unfreeze_requirements_r4_9d.md"
    requirements_md = _source_delivery_markdown(
        generated_at=generated_at,
        blockers_frozen=blockers_frozen,
        manual_count=manual_count,
        physical_count=physical_count,
        endpoint_count=endpoint_count,
        producer_count=producer_count,
        unknown_count=unknown_count,
        requirements_relpath="data/review_queue/source_delivery_required_r4_9d.csv",
    )
    write_markdown(root / requirements_md_relpath, requirements_md)
    unfreeze_requirements_written = True

    status_payload = {
        "generated_at": generated_at,
        "r4_9d_gate_passed": gate_passed,
        "r4_9d_blockers_frozen": blockers_frozen,
        "r4_9d_manual_file_required": manual_count,
        "r4_9d_physical_validated_file_missing": physical_count,
        "r4_9d_endpoint_delivery_blocked": endpoint_count,
        "r4_9d_producer_delivery_blocked": producer_count,
        "r4_9d_unknown_external_blocker": unknown_count,
        "r4_9d_retry_suppressed": retry_suppressed,
        "r4_9d_downstream_phases_blocked": downstream_blocked,
        "r4_9d_unfreeze_requirements_written": unfreeze_requirements_written,
        "r4_9d_downloads_executed": downloads_executed,
        "r4_9d_rows_ingested": rows_ingested,
        "r4_9d_production_inputs_staged": production_inputs_staged,
        "r4_9d_forbidden_artifact_usage": forbidden_artifact_usage,
        "production_status": production_status,
        "row_fabrication_policy": row_fabrication_policy,
        "phase_7_8_blocked": phase_7_8_blocked,
    }

    # Outputs
    write_json(exports_dir / "external_blocker_freeze_status_r4_9d.json", status_payload)
    write_csv(
        exports_dir / "external_blocker_freeze_matrix_r4_9d.csv",
        freeze_rows,
        [
            "frozen_at",
            "request_id",
            "request_type",
            "source_family",
            "expected_input",
            "target_output_path",
            "target_dropzone_path",
            "accepted_filename_patterns",
            "required_columns",
            "validation_command",
            "blocker_class",
            "reason_blocked",
            "next_action",
            "unfreeze_condition",
            "retry_rank_hint",
            "retry_reason_hint",
        ],
    )
    write_csv(
        review_dir / "source_delivery_required_r4_9d.csv",
        source_delivery_rows,
        [
            "expected_input",
            "source_family",
            "target_output_path",
            "target_dropzone_path",
            "accepted_filename_patterns",
            "required_columns",
            "validation_command",
            "reason_blocked",
            "unfreeze_condition",
            "blocker_class",
        ],
    )
    write_csv(
        review_dir / "retry_suppression_queue_r4_9d.csv",
        retry_suppression_rows,
        [
            "request_id",
            "expected_input",
            "source_family",
            "suppression_status",
            "suppression_reason",
            "suppression_scope",
            "unsuppress_condition",
            "retry_allowed",
        ],
    )
    write_csv(
        review_dir / "downstream_phase_blockers_r4_9d.csv",
        downstream_blocker_rows,
        ["phase_code", "blocked", "blocker_reason", "unfreeze_condition", "status"],
    )

    rebuild_status.update(
        {
            "r4_9d_generated_at": generated_at,
            "r4_9d_gate_passed": gate_passed,
            "r4_9d_blockers_frozen": blockers_frozen,
            "r4_9d_manual_file_required": manual_count,
            "r4_9d_physical_validated_file_missing": physical_count,
            "r4_9d_endpoint_delivery_blocked": endpoint_count,
            "r4_9d_producer_delivery_blocked": producer_count,
            "r4_9d_unknown_external_blocker": unknown_count,
            "r4_9d_retry_suppressed": retry_suppressed,
            "r4_9d_downstream_phases_blocked": downstream_blocked,
            "r4_9d_unfreeze_requirements_written": unfreeze_requirements_written,
            "r4_9d_downloads_executed": downloads_executed,
            "r4_9d_rows_ingested": rows_ingested,
            "r4_9d_production_inputs_staged": production_inputs_staged,
            "r4_9d_forbidden_artifact_usage": forbidden_artifact_usage,
            "production_status": production_status,
            "row_fabrication_policy": row_fabrication_policy,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
