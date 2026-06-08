"""R3 source coverage + master input audit.

Audits:
- source manifests
- raw/staging/normalized/master file presence and coverage
- pagination/capped/fixture signatures in source scripts
- master builder input retention

Goal: identify the source or builder stage causing constrained entity universe
collapse and keep Phase 7/8 blocked until R3 gates pass.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


YEAR_RANGE_DEFAULT = tuple(range(2000, 2026))
PAGINATION_TOKENS = ("page", "page_size", "offset", "next_page", "next", "cursor")
FIXTURE_TOKENS = ("fixture", "sample", "synthetic", "demo", "mock_data", "test_mode")
CAPPED_PATTERNS = (
    r"\.head\(\s*\d+\s*\)",
    r"nlargest\(\s*\d+",
    r"\btop_n\b",
    r"\blimit\s*=\s*(10|18|20|25|50|100)\b",
)


@dataclass(frozen=True)
class SourceSpec:
    source_system: str
    script_path: str
    file_patterns: tuple[str, ...]
    years_expected: tuple[int, ...]
    requires_pagination: bool
    endpoint_hint: str


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        "usaspending_awards",
        "scripts/auto_download.py",
        (
            "data/staging/processed/pr_contracts_master.csv",
            "data/staging/processed/pr_all_awards_master.csv",
        ),
        YEAR_RANGE_DEFAULT,
        True,
        "https://api.usaspending.gov",
    ),
    SourceSpec(
        "sam_entity_extract",
        "scripts/sam_enrichment.py",
        (
            "data/staging/processed/enrichment/vendor_uei_index.csv",
            "data/staging/processed/enrichment/master_enriched.csv",
        ),
        YEAR_RANGE_DEFAULT,
        True,
        "https://api.sam.gov",
    ),
    SourceSpec(
        "fsrs_subawards",
        "scripts/download_subawards.py",
        (
            "data/staging/processed/pr_subawards_master.csv",
            "data/staging/processed/pr_prime_sub_relationships.csv",
        ),
        YEAR_RANGE_DEFAULT,
        True,
        "https://api.usaspending.gov",
    ),
    SourceSpec(
        "fema_pa_hmgp",
        "scripts/download_fema.py",
        (
            "data/staging/processed/pr_fema_pa_master.csv",
            "data/staging/processed/pr_fema_hmgp_master.csv",
        ),
        YEAR_RANGE_DEFAULT,
        True,
        "https://www.fema.gov/openfema-data-page",
    ),
    SourceSpec(
        "hud_cdbg",
        "scripts/download_cdbg_dr.py",
        (
            "data/staging/processed/pr_cdbg_dr_master.csv",
            "data/staging/processed/pr_hud_master.csv",
        ),
        YEAR_RANGE_DEFAULT,
        True,
        "https://www.hudexchange.info",
    ),
    SourceSpec(
        "cor3",
        "scripts/download_cor3.py",
        ("data/staging/processed/pr_cor3_projects.csv",),
        YEAR_RANGE_DEFAULT,
        False,
        "https://www.cor3.pr.gov",
    ),
    SourceSpec(
        "prasa_aaa",
        "scripts/download_prasa.py",
        ("data/staging/processed/pr_prasa_contracts.csv",),
        YEAR_RANGE_DEFAULT,
        False,
        "https://www.acueductospr.com",
    ),
    SourceSpec(
        "prepa_luma_genera",
        "scripts/download_prepa_contracts.py",
        ("data/staging/processed/pr_prepa_contracts.csv",),
        YEAR_RANGE_DEFAULT,
        False,
        "https://aeepr.com",
    ),
    SourceSpec(
        "lda",
        "scripts/download_lda.py",
        ("data/staging/processed/pr_lda_filings.csv",),
        YEAR_RANGE_DEFAULT,
        True,
        "https://lda.senate.gov",
    ),
    SourceSpec(
        "pr_cabilderos",
        "scripts/download_cabilderos.py",
        ("data/staging/processed/pr_cabilderos.csv",),
        YEAR_RANGE_DEFAULT,
        False,
        "https://app.estado.pr.gov",
    ),
    SourceSpec(
        "emma_msrb_bonds",
        "scripts/download_emma.py",
        (
            "data/staging/processed/pr_emma_bonds.csv",
            "data/staging/processed/pr_emma_underwriters.csv",
            "data/staging/processed/pr_msrb_trades.csv",
        ),
        YEAR_RANGE_DEFAULT,
        True,
        "https://emma.msrb.org",
    ),
    SourceSpec(
        "fdic_banks",
        "scripts/download_fdic.py",
        (
            "data/staging/processed/pr_fdic_institutions.csv",
            "data/staging/processed/pr_fdic_financials.csv",
        ),
        YEAR_RANGE_DEFAULT,
        True,
        "https://banks.data.fdic.gov",
    ),
    SourceSpec(
        "cms_medicare",
        "scripts/download_cms.py",
        ("data/staging/processed/pr_cms_master.csv",),
        YEAR_RANGE_DEFAULT,
        True,
        "https://data.cms.gov",
    ),
    SourceSpec(
        "fec",
        "scripts/download_fec.py",
        ("data/staging/processed/pr_fec_contributions.csv",),
        YEAR_RANGE_DEFAULT,
        True,
        "https://api.open.fec.gov",
    ),
    SourceSpec(
        "municipal_contracts",
        "scripts/download_municipal.py",
        ("data/staging/processed/pr_municipal_contracts.csv",),
        YEAR_RANGE_DEFAULT,
        False,
        "https://www.comprasal.gov",
    ),
    SourceSpec(
        "ogpe_permits",
        "scripts/download_p3.py",
        ("data/staging/processed/pr_ogpe_permits.csv",),
        YEAR_RANGE_DEFAULT,
        False,
        "https://ogpe.pr.gov",
    ),
    SourceSpec(
        "act60_lihtc",
        "scripts/download_act60.py",
        (
            "data/staging/processed/pr_act60_decrees.csv",
            "data/staging/processed/pr_lihtc_projects.csv",
        ),
        YEAR_RANGE_DEFAULT,
        False,
        "https://www.hacienda.pr.gov",
    ),
    SourceSpec(
        "promesa_creditors",
        "scripts/download_promesa_creditors.py",
        ("data/staging/processed/pr_promesa_creditors.csv",),
        YEAR_RANGE_DEFAULT,
        False,
        "https://www.justice.gov",
    ),
    SourceSpec(
        "sf133",
        "scripts/download_sf133.py",
        ("data/staging/processed/pr_sf133_budget_execution.csv",),
        YEAR_RANGE_DEFAULT,
        True,
        "https://api.usaspending.gov",
    ),
    SourceSpec(
        "ofac",
        "scripts/download_ofac.py",
        ("data/staging/processed/pr_ofac_matches.csv",),
        YEAR_RANGE_DEFAULT,
        True,
        "https://sanctionslist.ofac.treas.gov",
    ),
)


REQUIRED_SOURCE_COLUMNS = (
    "source_system",
    "years_expected",
    "years_present",
    "year_coverage_pct",
    "rows_total",
    "rows_by_year",
    "field_completeness_pct",
    "pagination_complete",
    "capped_result_detected",
    "fixture_detected",
    "download_timestamp",
    "source_url_or_endpoint",
    "cache_source",
    "backfill_required",
)


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


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _row_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    if path.suffix.lower() != ".csv":
        return 0
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _extract_years_from_name(text: str) -> set[int]:
    years = set()
    for token in re.findall(r"(19\d{2}|20\d{2})", text):
        years.add(int(token))
    return years


def _extract_years_from_csv(path: Path) -> set[int]:
    years: set[int] = set()
    if not path.exists() or path.suffix.lower() != ".csv":
        return years
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for i, row in enumerate(reader):
            if i > 2000:
                break
            for key, value in row.items():
                if key is None:
                    continue
                key_norm = key.strip().lower()
                if key_norm not in {"fiscal_year", "year", "fy", "award_year"}:
                    continue
                yr = _safe_int(value)
                if 1900 <= yr <= 2100:
                    years.add(yr)
    return years


def _non_empty_ratio(values: list[str]) -> float:
    if not values:
        return 0.0
    non_empty = sum(1 for v in values if str(v).strip())
    return round(non_empty / len(values), 4)


def _first_url(text: str) -> str:
    match = re.search(r"https?://[^\s\"']+", text)
    return match.group(0) if match else ""


def _script_signals(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "has_pagination_tokens": False,
            "fixture_detected": False,
            "capped_detected": False,
            "endpoint": "",
            "text": "",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    return {
        "has_pagination_tokens": any(tok in lowered for tok in PAGINATION_TOKENS),
        "fixture_detected": any(tok in lowered for tok in FIXTURE_TOKENS),
        "capped_detected": any(re.search(pattern, lowered) for pattern in CAPPED_PATTERNS),
        "endpoint": _first_url(text),
        "text": text,
    }


def _has_manifest_for_file(path: Path) -> bool:
    candidates = (
        path.with_suffix(path.suffix + ".manifest.json"),
        path.parent / "manifest.json",
        path.parent / "_manifest.json",
    )
    return any(c.exists() for c in candidates)


def _scan_source_files(root: Path, spec: SourceSpec) -> list[Path]:
    files: list[Path] = []
    for rel in spec.file_patterns:
        p = root / rel
        if p.exists():
            files.append(p)
    # De-dup while preserving order.
    seen = set()
    out: list[Path] = []
    for p in files:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        out.append(p)
    return out


def _field_completeness_for_csv(path: Path) -> tuple[float, list[dict[str, Any]]]:
    if not path.exists() or path.suffix.lower() != ".csv":
        return 0.0, []

    id_cols = ("award_id", "contract_id", "id", "generated_internal_id", "project_id")
    name_cols = ("recipient_name", "vendor_name", "prime_recipient", "entity_name", "name")
    amount_cols = ("obligated_amount", "total_obligation", "amount", "total_flow", "par_amount")
    date_cols = ("award_date", "fiscal_year", "date", "year")
    lookup = {
        "id": id_cols,
        "recipient": name_cols,
        "amount": amount_cols,
        "date_or_year": date_cols,
    }

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        values_by_bucket: dict[str, list[str]] = {k: [] for k in lookup}
        for i, row in enumerate(reader):
            if i > 2000:
                break
            for bucket, candidates in lookup.items():
                value = ""
                for c in candidates:
                    if c in row and str(row.get(c, "")).strip():
                        value = str(row.get(c, ""))
                        break
                values_by_bucket[bucket].append(value)

    bucket_scores = {
        bucket: _non_empty_ratio(values) for bucket, values in values_by_bucket.items()
    }
    avg = round(sum(bucket_scores.values()) / max(len(bucket_scores), 1), 4)
    for bucket, score in bucket_scores.items():
        rows.append(
            {
                "file_path": str(path),
                "field_group": bucket,
                "completeness_pct": round(score * 100, 2),
            }
        )
    return avg, rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _parse_builder_inputs(build_script: Path) -> tuple[list[str], list[str]]:
    if not build_script.exists():
        return [], []
    text = build_script.read_text(encoding="utf-8", errors="replace")
    mod = ast.parse(text)
    new_masters: list[str] = []
    expansion: list[str] = []
    for node in mod.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "NEW_MASTERS":
                try:
                    value = ast.literal_eval(node.value)
                    new_masters = [x[0] for x in value]
                except Exception:
                    pass
            if isinstance(target, ast.Name) and target.id == "EXPANSION_FILES":
                try:
                    value = ast.literal_eval(node.value)
                    expansion = list(value)
                except Exception:
                    pass
    return new_masters, expansion


def _infer_master_collapse_cause(root: Path) -> dict[str, Any]:
    build_script = root / "scripts/build_unified_master.py"
    dedup_script = root / "scripts/deduplicate_master.py"
    report_summary = _read_json(root / "data/reports/pr_report_summary.json")
    dominance_summary = _read_json(root / "data/staging/processed/dominance_summary.json")
    awards_summary = _read_json(root / "data/staging/processed/pr_all_awards_summary.json")

    new_masters, expansion_files = _parse_builder_inputs(build_script)
    processed_dir = root / "data/staging/processed"
    expansion_dir = root / "data/staging/expansion"
    expected = (
        [processed_dir / "pr_contracts_master.csv"]
        + [processed_dir / f for f in new_masters]
        + [expansion_dir / f for f in expansion_files]
    )
    present = [p for p in expected if p.exists()]
    present_rows = sum(_row_count(p) for p in present)
    present_count = len(present)
    expected_count = len(expected)

    unique_entities = _safe_int(
        awards_summary.get("unique_recipients")
        or dominance_summary.get("unique_vendors")
        or report_summary.get("awards", {}).get("unique_entities")
    )
    total_rows = _safe_int(awards_summary.get("total_rows") or dominance_summary.get("total_rows"))

    build_text = (
        build_script.read_text(encoding="utf-8", errors="replace") if build_script.exists() else ""
    )
    dedup_text = (
        dedup_script.read_text(encoding="utf-8", errors="replace") if dedup_script.exists() else ""
    )
    builder_topn_signal = (
        ("top_n" in build_text.lower())
        or ("head(" in build_text.lower())
        or ("nlargest(" in build_text.lower())
    )
    dedup_aggressive_signal = ("drop_duplicates" in dedup_text.lower()) and (
        "vendor_name" in dedup_text.lower() or "recipient_name" in dedup_text.lower()
    )

    if unique_entities <= 18 and present_count == 0 and total_rows > 0:
        cause = "build_unified_master_input_gap_with_stale_summary_replay"
        detail = "Declared build_unified_master inputs are absent while summary artifacts report populated rows."
    elif unique_entities <= 18 and present_count < max(1, expected_count // 4):
        cause = "build_unified_master_input_gap_partial_ingest"
        detail = "Only a small fraction of declared master inputs exist; collapse likely caused upstream of entity resolution."
    elif unique_entities <= 18 and builder_topn_signal:
        cause = "build_unified_master_topn_or_cap_signature"
        detail = (
            "Builder script contains top-N/capping signatures and constrained output cardinality."
        )
    elif unique_entities <= 18 and dedup_aggressive_signal:
        cause = "deduplicate_master_aggressive_entity_dedup_signature"
        detail = "Dedup script indicates potential vendor-level collapse behavior."
    else:
        cause = "source_or_builder_cause_not_determined"
        detail = "No single collapse trigger inferred from available artifacts."

    return {
        "r3_primary_collapse_cause": cause,
        "r3_primary_collapse_cause_detail": detail,
        "builder_expected_input_count": expected_count,
        "builder_present_input_count": present_count,
        "builder_present_input_rows": present_rows,
        "builder_missing_inputs": [str(p.relative_to(root)) for p in expected if not p.exists()],
        "unique_entities_observed": unique_entities,
        "rows_observed": total_rows,
    }


def run_audit(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data/exports"
    review_dir = root / "data/review_queue"
    prior_rebuild = _read_json(root / "data/exports/rebuild_status.json")

    source_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    backfill_rows: list[dict[str, Any]] = []

    for spec in SOURCE_SPECS:
        script_path = root / spec.script_path
        script_sig = _script_signals(script_path)
        files = _scan_source_files(root, spec)
        rows_total = sum(_row_count(p) for p in files if p.suffix.lower() == ".csv")

        years_present_set: set[int] = set()
        for file in files:
            years_present_set.update(_extract_years_from_name(str(file)))
            if file.suffix.lower() == ".csv":
                years_present_set.update(_extract_years_from_csv(file))
        years_present = sorted(y for y in years_present_set if y in spec.years_expected)
        year_coverage_pct = round(len(years_present) / max(len(spec.years_expected), 1), 4)

        completeness = 0.0
        sample_csv = next((p for p in files if p.suffix.lower() == ".csv"), None)
        if sample_csv:
            completeness, details = _field_completeness_for_csv(sample_csv)
            for detail in details:
                field_rows.append(
                    {
                        "source_system": spec.source_system,
                        "file_path": detail["file_path"],
                        "field_group": detail["field_group"],
                        "completeness_pct": detail["completeness_pct"],
                    }
                )

        pagination_complete = (not spec.requires_pagination) or bool(
            script_sig["has_pagination_tokens"]
        )
        capped_result_detected = bool(
            script_sig["capped_detected"] and (not pagination_complete or rows_total <= 1000)
        )
        fixture_detected = bool(script_sig["fixture_detected"])
        manifest_missing_count = sum(1 for p in files if not _has_manifest_for_file(p))

        if rows_total > 0:
            cache_source = "raw_or_processed_files_present"
        elif files:
            cache_source = "non_csv_source_files_only"
        else:
            cache_source = "missing_source_files"

        download_timestamp = ""
        if files:
            latest = max(p.stat().st_mtime for p in files)
            download_timestamp = datetime.fromtimestamp(latest, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        backfill_required = bool(
            rows_total == 0
            or year_coverage_pct < 0.95
            or completeness < 0.8
            or not pagination_complete
            or capped_result_detected
            or fixture_detected
            or manifest_missing_count > 0
        )

        years_expected_str = f"{min(spec.years_expected)}-{max(spec.years_expected)}"
        years_present_str = ",".join(str(y) for y in years_present)
        rows_by_year = ""
        if years_present:
            rows_by_year = "|".join(f"{y}:?" for y in years_present[:20])

        source_rows.append(
            {
                "source_system": spec.source_system,
                "years_expected": years_expected_str,
                "years_present": years_present_str,
                "year_coverage_pct": round(year_coverage_pct * 100, 2),
                "rows_total": rows_total,
                "rows_by_year": rows_by_year,
                "field_completeness_pct": round(completeness * 100, 2),
                "pagination_complete": pagination_complete,
                "capped_result_detected": capped_result_detected,
                "fixture_detected": fixture_detected,
                "download_timestamp": download_timestamp,
                "source_url_or_endpoint": script_sig["endpoint"] or spec.endpoint_hint,
                "cache_source": cache_source,
                "backfill_required": backfill_required,
            }
        )

        if backfill_required:
            reasons: list[str] = []
            if rows_total == 0:
                reasons.append("no source rows found")
            if year_coverage_pct < 0.95:
                reasons.append("year coverage below 95%")
            if completeness < 0.8:
                reasons.append("field completeness below 80%")
            if not pagination_complete:
                reasons.append("missing pagination signature in script")
            if capped_result_detected:
                reasons.append("capped/top-N signature detected")
            if fixture_detected:
                reasons.append("fixture/demo signature detected")
            if manifest_missing_count > 0:
                reasons.append(f"{manifest_missing_count} files missing manifest metadata")

            backfill_rows.append(
                {
                    "source_system": spec.source_system,
                    "priority": len(backfill_rows) + 1,
                    "script_path": spec.script_path,
                    "rows_total": rows_total,
                    "year_coverage_pct": round(year_coverage_pct * 100, 2),
                    "field_completeness_pct": round(completeness * 100, 2),
                    "manifest_missing_count": manifest_missing_count,
                    "recommended_action": "; ".join(reasons),
                }
            )

    collapse = _infer_master_collapse_cause(root)

    # Add master-builder audit line into source coverage table.
    builder_backfill = collapse["builder_present_input_count"] < max(
        1, collapse["builder_expected_input_count"] // 2
    )
    source_rows.append(
        {
            "source_system": "master_builder.build_unified_master",
            "years_expected": "n/a",
            "years_present": "n/a",
            "year_coverage_pct": 0.0,
            "rows_total": collapse["builder_present_input_rows"],
            "rows_by_year": "n/a",
            "field_completeness_pct": 0.0,
            "pagination_complete": True,
            "capped_result_detected": False,
            "fixture_detected": "stale_summary_replay" in collapse["r3_primary_collapse_cause"],
            "download_timestamp": "",
            "source_url_or_endpoint": "local builder",
            "cache_source": f"{collapse['builder_present_input_count']}/{collapse['builder_expected_input_count']} declared inputs present",
            "backfill_required": builder_backfill,
        }
    )
    if builder_backfill:
        backfill_rows.insert(
            0,
            {
                "source_system": "master_builder.build_unified_master",
                "priority": 0,
                "script_path": "scripts/build_unified_master.py",
                "rows_total": collapse["builder_present_input_rows"],
                "year_coverage_pct": 0.0,
                "field_completeness_pct": 0.0,
                "manifest_missing_count": collapse["builder_expected_input_count"]
                - collapse["builder_present_input_count"],
                "recommended_action": collapse["r3_primary_collapse_cause_detail"],
            },
        )

    _write_csv(
        exports_dir / "source_coverage_audit.csv", source_rows, list(REQUIRED_SOURCE_COLUMNS)
    )
    _write_csv(
        exports_dir / "source_field_completeness.csv",
        field_rows,
        ["source_system", "file_path", "field_group", "completeness_pct"],
    )
    _write_csv(
        review_dir / "source_backfill_queue.csv",
        backfill_rows,
        [
            "source_system",
            "priority",
            "script_path",
            "rows_total",
            "year_coverage_pct",
            "field_completeness_pct",
            "manifest_missing_count",
            "recommended_action",
        ],
    )

    # R3 gate.
    production_source_rows = [
        row for row in source_rows if not str(row["source_system"]).startswith("master_builder.")
    ]
    active_sources = [row for row in production_source_rows if row.get("rows_total", 0) > 0]
    coverage_gate = bool(active_sources) and all(
        float(row.get("year_coverage_pct", 0)) >= 95.0 for row in active_sources
    )
    backfill_gate = len(backfill_rows) == 0
    collapse_gate = collapse["r3_primary_collapse_cause"] not in {
        "build_unified_master_input_gap_with_stale_summary_replay",
        "build_unified_master_input_gap_partial_ingest",
        "build_unified_master_topn_or_cap_signature",
        "deduplicate_master_aggressive_entity_dedup_signature",
    }
    r3_gate_passed = bool(coverage_gate and backfill_gate and collapse_gate)

    prior_phase_block = bool(prior_rebuild.get("phase_7_8_blocked"))
    phase_7_8_blocked = bool(prior_phase_block or (not r3_gate_passed))

    rebuild_status = dict(prior_rebuild)
    rebuild_status.update(
        {
            "r3_generated_at": _utc_now(),
            "r3_gate_passed": r3_gate_passed,
            "phase_7_8_blocked": phase_7_8_blocked,
            "phase_7_8_block_reason": (
                "R3 gate failed and/or prior phase gate still blocked"
                if phase_7_8_blocked
                else "R3 gate passed and no prior gate block remains"
            ),
            "source_coverage_gate_passed": coverage_gate,
            "source_backfill_queue_empty": backfill_gate,
            "master_collapse_cause_gate_passed": collapse_gate,
            **collapse,
            "r3_outputs": {
                "source_coverage_audit": "data/exports/source_coverage_audit.csv",
                "source_field_completeness": "data/exports/source_field_completeness.csv",
                "source_backfill_queue": "data/review_queue/source_backfill_queue.csv",
            },
        }
    )
    _write_json(root / "data/exports/rebuild_status.json", rebuild_status)
    return rebuild_status
