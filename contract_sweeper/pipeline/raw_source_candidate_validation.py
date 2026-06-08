"""Raw source candidate validation helpers for R4.9H."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.acquisition_package import safe_int, split_pipe
from contract_sweeper.pipeline.delivered_source_validation import contains_forbidden_token

DERIVABLE_CANONICAL_COLUMNS = {
    "recipient_name_normalized",
    "recipient_uei",
    "pop_county",
    "description",
    "source_dataset",
    "award_category",
    "source_system",
    "source_record_id",
    "source_lineage_path",
    "source_lineage_mode",
}

USAS_CANONICAL_COLUMN_MAP = {
    "award_id": {
        "contract_id",
        "award_id",
        "generated_unique_award_id",
        "assistance_award_unique_key",
    },
    "recipient_name": {"vendor_name", "recipient_name", "legal_business_name"},
    "recipient_name_normalized": {"normalized_vendor", "recipient_name_normalized"},
    "recipient_uei": {"recipient_uei", "recipient_unique_id", "uei"},
    "awarding_agency": {"agency_name", "awarding_agency", "awarding_agency_name"},
    "awarding_sub_agency": {"sub_agency", "awarding_sub_agency", "awarding_subagency_name"},
    "obligated_amount": {
        "amount_usd",
        "obligated_amount",
        "federal_action_obligation",
        "total_obligation",
    },
    "award_date": {"award_date", "action_date", "start_date", "period_of_performance_start_date"},
    "fiscal_year": {"fiscal_year"},
    "pop_state": {"pop_state", "place_of_performance_state_code", "place_of_performance_state"},
    "pop_county": {"pop_county", "place_of_performance_county_name", "place_of_performance_city"},
    "description": {"description", "award_description", "transaction_description"},
    "source_file": {"source_file", "raw_source_file"},
}

TARGET_TYPE_HINTS = {
    "pr_grants_master.csv": {"grants", "unknown_usaspending"},
    "pr_subawards_master.csv": {"subawards", "unknown_usaspending"},
    "pr_fema_pa_master.csv": {"grants", "unknown_usaspending"},
    "pr_fema_hmgp_master.csv": {"grants", "unknown_usaspending"},
    "pr_research_master.csv": {"grants", "unknown_usaspending"},
    "pr_sba_loans_master.csv": {"grants", "unknown_usaspending"},
    "pr_cdbg_dr_master.csv": {"grants", "unknown_usaspending"},
}


def normalized_columns(columns: list[str] | set[str]) -> set[str]:
    return {str(column).strip().lower() for column in columns if str(column).strip()}


def classify_source_type(path_text: str, columns: list[str] | set[str]) -> str:
    lowered = str(path_text or "").lower()
    cols = normalized_columns(columns)

    if "subaward" in lowered or any("subaward" in col for col in cols):
        return "subawards"
    if "idv" in lowered or "indirect" in lowered:
        return "idv_indirect_awards"
    if "dod" in lowered or "upr" in lowered:
        return "dod_upr_expansion"
    if "reconstruction" in lowered:
        return "reconstruction_expansion"
    if "grant" in lowered or "assistance" in lowered or "cfda" in lowered:
        return "grants"
    if "contract" in lowered or "fpds" in lowered or "procurement" in lowered:
        return "contracts"
    if {
        "recipient_name",
        "award_id",
        "total_obligation",
    }.issubset(cols) or {
        "vendor_name",
        "agency_name",
        "contract_id",
        "amount_usd",
    }.issubset(cols):
        return "unknown_usaspending"
    return "unknown_usaspending" if "usas" in lowered or "usaspending" in lowered else "unknown"


def is_usaspending_like(path_text: str, columns: list[str] | set[str]) -> bool:
    lowered = str(path_text or "").lower()
    cols = normalized_columns(columns)
    path_match = any(
        token in lowered
        for token in (
            "usas",
            "usaspending",
            "all_contracts",
            "all_assistance",
            "primeawards",
            "prime_transactions",
            "subaward",
        )
    )
    column_match = bool(
        {
            "award_id",
            "recipient_name",
        }.issubset(cols)
        or {
            "contract_id",
            "vendor_name",
            "agency_name",
        }.issubset(cols)
        or {
            "generated_unique_award_id",
            "recipient_name",
        }.issubset(cols)
    )
    return path_match or column_match


def target_can_match_source(
    *,
    target_row: dict[str, str],
    source_type: str,
) -> bool:
    target_output = str(
        target_row.get("target_output_path") or target_row.get("expected_input") or ""
    ).strip()
    target_name = Path(target_output).name
    source_family = str(target_row.get("source_family", "")).strip()

    if source_family not in {
        "usaspending_federal_awards_backbone",
        "fsrs_subawards",
        "fema_pa_hmgp",
        "federal_research",
        "sba_loans",
        "hud_cdbg",
    }:
        return False

    allowed = TARGET_TYPE_HINTS.get(target_name)
    if allowed:
        return source_type in allowed
    return source_type == "unknown_usaspending"


def _find_mapped_column(required: str, columns: set[str]) -> str:
    candidates = USAS_CANONICAL_COLUMN_MAP.get(required, set())
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return ""


def validate_raw_candidate(
    *,
    target_row: dict[str, str],
    inventory_row: dict[str, Any],
) -> dict[str, Any]:
    columns = [piece for piece in str(inventory_row.get("columns", "")).split("|") if piece.strip()]
    actual = normalized_columns(columns)
    required = split_pipe(
        target_row.get("required_columns") or target_row.get("required_columns/profile") or ""
    )
    required_norm = [column.strip().lower() for column in required if column.strip()]

    display_path = str(inventory_row.get("display_path", "")).strip()
    source_type = str(inventory_row.get("likely_source_type", "")).strip()
    row_count = safe_int(inventory_row.get("row_count"))
    validation_status = "rejected"
    validation_reason = ""
    mapping_profile = ""
    missing_columns: list[str] = []
    mapped_columns: list[str] = []

    if contains_forbidden_token(display_path):
        validation_reason = "candidate_forbidden_artifact_path"
    elif row_count <= 0:
        validation_reason = "raw_candidate_empty_or_row_count_unknown"
    elif not target_can_match_source(target_row=target_row, source_type=source_type):
        validation_reason = "raw_source_type_not_applicable_to_target"
    else:
        exact_missing = [column for column in required_norm if column not in actual]
        if not exact_missing:
            validation_status = "validated"
            validation_reason = "exact_required_columns_present"
            mapping_profile = "exact_required_columns"
        else:
            for required_column in exact_missing:
                mapped = _find_mapped_column(required_column, actual)
                if mapped:
                    mapped_columns.append(f"{required_column}<-{mapped}")
                elif required_column in DERIVABLE_CANONICAL_COLUMNS:
                    mapped_columns.append(f"{required_column}<-deterministic_derivation")
                else:
                    missing_columns.append(required_column)

            if missing_columns:
                validation_reason = "raw_missing_required_or_mappable_columns:" + "|".join(
                    sorted(missing_columns)
                )
                mapping_profile = "unmappable_raw_export"
            else:
                validation_status = "validated"
                validation_reason = "deterministic_usaspending_mapping_available"
                mapping_profile = "deterministic_usaspending_raw_to_canonical"

    return {
        "expected_input": str(target_row.get("expected_input", "")).strip(),
        "source_family": str(target_row.get("source_family", "")).strip(),
        "blocker_class": str(target_row.get("blocker_class", "")).strip(),
        "target_output_path": str(target_row.get("target_output_path", "")).strip(),
        "target_dropzone_path": str(target_row.get("target_dropzone_path", "")).strip(),
        "raw_display_path": display_path,
        "raw_container_path": str(inventory_row.get("container_path", "")).strip(),
        "raw_member_path": str(inventory_row.get("member_path", "")).strip(),
        "raw_extension": str(inventory_row.get("extension", "")).strip(),
        "raw_row_count": row_count,
        "raw_sha256": str(inventory_row.get("sha256", "")).strip(),
        "likely_source_type": source_type,
        "required_columns": "|".join(required),
        "raw_columns": str(inventory_row.get("columns", "")).strip(),
        "mapped_columns": "|".join(mapped_columns),
        "missing_columns": "|".join(sorted(missing_columns)),
        "mapping_profile": mapping_profile,
        "validation_status": validation_status,
        "validation_reason": validation_reason,
    }
