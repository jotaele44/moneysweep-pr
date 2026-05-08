"""Tests for R4.8D targeted retry and schema alignment."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from contract_sweeper.pipeline.targeted_backfill_retry import run_targeted_backfill_retry


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap(tmp_path: Path) -> None:
    # Producer script that writes one valid row.
    producer_ok = tmp_path / "scripts" / "producer_ok.py"
    producer_ok.parent.mkdir(parents=True, exist_ok=True)
    producer_ok.write_text(
        """
from pathlib import Path
import pandas as pd
p = Path('data/staging/processed/source_ok.csv')
p.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame([{'award_id':'A1','recipient_name':'Acme','source_dataset':'test'}]).to_csv(p, index=False)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    # Schema source script writes row with canonical minimum but missing lineage columns.
    schema_script = tmp_path / "scripts" / "schema_source.py"
    schema_script.write_text(
        """
from pathlib import Path
import pandas as pd
p = Path('data/staging/processed/source_schema.csv')
p.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame([{'award_id':'S1','recipient_name':'Schema Co','source_dataset':'schema_ds','source_file':'schema.csv'}]).to_csv(p, index=False)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    # No-data script writes header-only file.
    nodata_script = tmp_path / "scripts" / "nodata.py"
    nodata_script.write_text(
        """
from pathlib import Path
import pandas as pd
p = Path('data/staging/processed/source_nodata.csv')
p.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame(columns=['award_id','recipient_name']).to_csv(p, index=False)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    remediation_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/source_ok.csv",
            "source_family": "family_ok",
            "target_output_path": "data/staging/processed/source_ok.csv",
            "terminal_status": "execution_failed",
            "primary_blocker_class": "producer_exception",
            "next_action": "patch_producer_script",
            "reason": "command failed",
            "producer_script": "scripts/producer_ok.py",
            "source_url_or_portal": "https://example.test/ok",
            "required_env_vars": "",
            "missing_env_vars": "",
            "validation_command": "python -c \"print('ok')\"",
            "acceptance_gate": "rows>0",
            "recommended_action_r46": "retry",
            "forbidden_artifact_usage": "False",
        },
        {
            "priority": 2,
            "expected_input": "data/staging/processed/source_schema.csv",
            "source_family": "family_schema",
            "target_output_path": "data/staging/processed/source_schema.csv",
            "terminal_status": "schema_failure",
            "primary_blocker_class": "schema_mismatch",
            "next_action": "add_schema_mapping",
            "reason": "missing required columns",
            "producer_script": "scripts/schema_source.py",
            "source_url_or_portal": "https://example.test/schema",
            "required_env_vars": "",
            "missing_env_vars": "",
            "validation_command": "python -c \"print('schema valid')\"",
            "acceptance_gate": "rows>0",
            "recommended_action_r46": "retry",
            "forbidden_artifact_usage": "False",
        },
        {
            "priority": 3,
            "expected_input": "data/staging/processed/source_nodata.csv",
            "source_family": "family_nodata",
            "target_output_path": "data/staging/processed/source_nodata.csv",
            "terminal_status": "no_data",
            "primary_blocker_class": "no_data",
            "next_action": "retry_after_fix",
            "reason": "target output not produced",
            "producer_script": "scripts/nodata.py",
            "source_url_or_portal": "https://example.test/nodata",
            "required_env_vars": "",
            "missing_env_vars": "",
            "validation_command": "python -c \"print('nodata')\"",
            "acceptance_gate": "rows>0",
            "recommended_action_r46": "retry",
            "forbidden_artifact_usage": "False",
        },
        {
            "priority": 4,
            "expected_input": "data/staging/processed/source_endpoint.csv",
            "source_family": "family_endpoint",
            "target_output_path": "data/staging/processed/source_endpoint.csv",
            "terminal_status": "execution_timeout",
            "primary_blocker_class": "endpoint_unavailable",
            "next_action": "endpoint_review",
            "reason": "command timed out",
            "producer_script": "scripts/endpoint.py",
            "source_url_or_portal": "https://example.test/endpoint",
            "required_env_vars": "",
            "missing_env_vars": "",
            "validation_command": "",
            "acceptance_gate": "rows>0",
            "recommended_action_r46": "endpoint review",
            "forbidden_artifact_usage": "False",
        },
    ]

    _write_csv(
        tmp_path / "data" / "exports" / "backfill_failure_remediation_matrix_r4_8c.csv",
        remediation_rows,
        list(remediation_rows[0].keys()),
    )

    _write_json(
        tmp_path / "data" / "exports" / "backfill_failure_remediation_status_r4_8c.json",
        {
            "r4_8c_gate_passed": True,
            "r4_8c_total_failed_sources": 4,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "source_producer_fix_queue_r4_8c.csv",
        [
            {
                "priority": 1,
                "expected_input": "data/staging/processed/source_ok.csv",
                "source_family": "family_ok",
                "producer_script": "scripts/producer_ok.py",
                "error_type": "producer_exception",
                "stderr_excerpt_safe": "",
                "timeout_seconds": "",
                "recommended_patch": "retry",
                "next_action": "patch_producer_script",
            }
        ],
        [
            "priority",
            "expected_input",
            "source_family",
            "producer_script",
            "error_type",
            "stderr_excerpt_safe",
            "timeout_seconds",
            "recommended_patch",
            "next_action",
        ],
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "schema_remediation_queue_r4_8c.csv",
        [
            {
                "priority": 2,
                "expected_input": "data/staging/processed/source_schema.csv",
                "source_family": "family_schema",
                "observed_columns": "award_id|recipient_name|source_dataset|source_file",
                "required_columns": "award_id|recipient_name|recipient_name_normalized|source_system|source_record_id|source_lineage_path|source_lineage_mode",
                "missing_columns": "recipient_name_normalized|source_system|source_record_id|source_lineage_path|source_lineage_mode",
                "candidate_column_aliases": "{}",
                "recommended_mapping": json.dumps(
                    {
                        "recipient_name_normalized": "recipient_name",
                        "source_system": "source_dataset",
                        "source_record_id": "award_id",
                        "source_lineage_path": "source_file",
                        "source_lineage_mode": "source_dataset",
                    }
                ),
                "next_action": "add_schema_mapping",
            }
        ],
        [
            "priority",
            "expected_input",
            "source_family",
            "observed_columns",
            "required_columns",
            "missing_columns",
            "candidate_column_aliases",
            "recommended_mapping",
            "next_action",
        ],
    )

    manual_rows = []
    for row in remediation_rows:
        manual_rows.append(
            {
                "priority": row["priority"],
                "source_family": row["source_family"],
                "expected_input": row["expected_input"],
                "source_url_or_portal": row["source_url_or_portal"],
                "required_file_type": "csv",
                "accepted_filename_patterns": "*.csv",
                "required_columns": "award_id|recipient_name",
                "target_dropzone_path": f"data/manual_import_dropzone/{Path(row['expected_input']).name}",
                "target_output_path": row["target_output_path"],
                "validation_command": row["validation_command"],
            }
        )

    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_fallback_execution_queue_r4_8c.csv",
        manual_rows,
        [
            "priority",
            "source_family",
            "expected_input",
            "source_url_or_portal",
            "required_file_type",
            "accepted_filename_patterns",
            "required_columns",
            "target_dropzone_path",
            "target_output_path",
            "validation_command",
        ],
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "source_endpoint_review_queue_r4_8c.csv",
        [
            {
                "priority": 4,
                "expected_input": "data/staging/processed/source_endpoint.csv",
                "source_family": "family_endpoint",
                "source_url_or_portal": "https://example.test/endpoint",
                "producer_script": "scripts/endpoint.py",
                "reason": "timeout",
                "recommended_review": "review",
                "next_action": "endpoint_review",
            }
        ],
        [
            "priority",
            "expected_input",
            "source_family",
            "source_url_or_portal",
            "producer_script",
            "reason",
            "recommended_review",
            "next_action",
        ],
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8c.csv",
        [
            {
                "retry_rank": idx + 1,
                "priority": row["priority"],
                "expected_input": row["expected_input"],
                "source_family": row["source_family"],
                "primary_blocker_class": row["primary_blocker_class"],
                "next_action": row["next_action"],
                "retry_instruction": "retry",
            }
            for idx, row in enumerate(remediation_rows)
        ],
        [
            "retry_rank",
            "priority",
            "expected_input",
            "source_family",
            "primary_blocker_class",
            "next_action",
            "retry_instruction",
        ],
    )

    execution_rows = [
        {
            "priority": 1,
            "expected_input": "data/staging/processed/source_ok.csv",
            "source_family": "family_ok",
            "readiness": "ready_for_execute_downloads",
            "terminal_status": "execution_failed",
            "attempted": "True",
            "skipped_reason": "",
            "target_output_path": "data/staging/processed/source_ok.csv",
            "producer_script": "scripts/producer_ok.py",
            "command": "python scripts/producer_ok.py",
            "command_executed": "True",
            "command_exit_code": "1",
            "required_env_vars": "",
            "missing_env_vars": "",
            "output_exists": "False",
            "row_count": "0",
            "schema_valid": "False",
            "validation_command": "python -c \"print('ok')\"",
            "validation_executed": "False",
            "validation_exit_code": "",
            "validated_manifest_path": "",
            "validated_manifest_written": "False",
            "blocker_reason": "failed",
            "next_action": "retry",
            "forbidden_artifact_usage": "False",
            "target_hash_before": "",
            "target_hash_after": "",
            "target_changed": "False",
            "target_sha256": "",
        },
        {
            "priority": 2,
            "expected_input": "data/staging/processed/source_schema.csv",
            "source_family": "family_schema",
            "readiness": "ready_for_execute_downloads",
            "terminal_status": "schema_failure",
            "attempted": "True",
            "skipped_reason": "",
            "target_output_path": "data/staging/processed/source_schema.csv",
            "producer_script": "scripts/schema_source.py",
            "command": "python scripts/schema_source.py",
            "command_executed": "True",
            "command_exit_code": "0",
            "required_env_vars": "",
            "missing_env_vars": "",
            "output_exists": "True",
            "row_count": "1",
            "schema_valid": "False",
            "validation_command": "python -c \"print('schema valid')\"",
            "validation_executed": "False",
            "validation_exit_code": "",
            "validated_manifest_path": "",
            "validated_manifest_written": "False",
            "blocker_reason": "schema",
            "next_action": "retry",
            "forbidden_artifact_usage": "False",
            "target_hash_before": "",
            "target_hash_after": "",
            "target_changed": "False",
            "target_sha256": "",
        },
        {
            "priority": 3,
            "expected_input": "data/staging/processed/source_nodata.csv",
            "source_family": "family_nodata",
            "readiness": "ready_for_execute_downloads",
            "terminal_status": "no_data",
            "attempted": "True",
            "skipped_reason": "",
            "target_output_path": "data/staging/processed/source_nodata.csv",
            "producer_script": "scripts/nodata.py",
            "command": "python scripts/nodata.py",
            "command_executed": "True",
            "command_exit_code": "0",
            "required_env_vars": "",
            "missing_env_vars": "",
            "output_exists": "False",
            "row_count": "0",
            "schema_valid": "False",
            "validation_command": "python -c \"print('nodata')\"",
            "validation_executed": "False",
            "validation_exit_code": "",
            "validated_manifest_path": "",
            "validated_manifest_written": "False",
            "blocker_reason": "nodata",
            "next_action": "retry",
            "forbidden_artifact_usage": "False",
            "target_hash_before": "",
            "target_hash_after": "",
            "target_changed": "False",
            "target_sha256": "",
        },
        {
            "priority": 4,
            "expected_input": "data/staging/processed/source_endpoint.csv",
            "source_family": "family_endpoint",
            "readiness": "ready_for_execute_downloads",
            "terminal_status": "execution_timeout",
            "attempted": "True",
            "skipped_reason": "",
            "target_output_path": "data/staging/processed/source_endpoint.csv",
            "producer_script": "scripts/endpoint.py",
            "command": "python scripts/endpoint.py",
            "command_executed": "True",
            "command_exit_code": "124",
            "required_env_vars": "",
            "missing_env_vars": "",
            "output_exists": "False",
            "row_count": "0",
            "schema_valid": "False",
            "validation_command": "",
            "validation_executed": "False",
            "validation_exit_code": "",
            "validated_manifest_path": "",
            "validated_manifest_written": "False",
            "blocker_reason": "timeout",
            "next_action": "endpoint",
            "forbidden_artifact_usage": "False",
            "target_hash_before": "",
            "target_hash_after": "",
            "target_changed": "False",
            "target_sha256": "",
        },
    ]

    _write_csv(
        tmp_path / "data" / "exports" / "controlled_backfill_execution_results_r4_8b.csv",
        execution_rows,
        list(execution_rows[0].keys()),
    )

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )


def test_r48d_runs_targeted_retry_and_writes_outputs(tmp_path: Path):
    _bootstrap(tmp_path)

    status = run_targeted_backfill_retry(tmp_path, command_timeout_s=30, validation_timeout_s=30)

    assert status["r4_8d_gate_passed"] is True
    assert status["r4_8d_total_sources_considered"] == 4
    assert status["r4_8d_sources_retried"] == 3
    assert status["r4_8d_successful_sources"] == 2
    assert status["r4_8d_failed_sources"] == 1
    assert status["r4_8d_rows_ingested"] == 2
    assert status["r4_8d_production_inputs_staged"] == 2
    assert status["r4_8d_validated_source_manifests_written"] == 2
    assert status["r4_8d_unresolved_endpoint_failures"] == 1
    assert status["r4_8d_unresolved_schema_failures"] == 0
    assert status["r4_8d_unresolved_producer_failures"] == 1
    assert status["r4_8d_forbidden_artifact_usage"] is False
    assert status["phase_7_8_blocked"] is True

    manifests = list(
        csv.DictReader(
            (tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8d.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(manifests) == 2


def test_r48d_rejects_forbidden_artifact_paths(tmp_path: Path):
    _bootstrap(tmp_path)

    matrix_path = tmp_path / "data" / "exports" / "backfill_failure_remediation_matrix_r4_8c.csv"
    rows = list(csv.DictReader(matrix_path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/source_report.csv"
    _write_csv(matrix_path, rows, list(rows[0].keys()))

    status = run_targeted_backfill_retry(tmp_path)

    assert status["r4_8d_forbidden_artifact_usage"] is True
    assert status["r4_8d_gate_passed"] is False


def test_r48d_schema_alignment_report_records_deterministic_mappings(tmp_path: Path):
    _bootstrap(tmp_path)

    run_targeted_backfill_retry(tmp_path)

    report = list(
        csv.DictReader(
            (tmp_path / "data" / "exports" / "schema_alignment_report_r4_8d.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert any(r["expected_input"] == "data/staging/processed/source_schema.csv" for r in report)
    target = [r for r in report if r["expected_input"] == "data/staging/processed/source_schema.csv"][0]
    assert target["alignment_status"] in {"aligned", "already_aligned"}
    assert int(target["alignment_added_count"]) >= 1
