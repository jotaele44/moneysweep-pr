from scripts.validate_source_registry_top_form import (
    ALLOWED_REFRESH,
    CSV_REPORT,
    MD_REPORT,
    OPERATOR_REVIEW_REQUIRED,
    REQUIRED_COLUMNS,
    build_alignment,
    infer_blocker_type,
    infer_intake_mode,
    infer_refresh_frequency,
    validate,
    write_csv,
    write_markdown,
)


def test_source_registry_top_form_alignment_has_rows():
    rows = build_alignment()
    assert rows
    assert len(rows) >= 80


def test_source_registry_top_form_alignment_columns_present():
    rows = build_alignment()
    for row in rows:
        for column in REQUIRED_COLUMNS:
            assert column in row


def test_source_registry_top_form_alignment_has_no_structural_errors():
    rows = build_alignment()
    assert validate(rows) == []


def test_refresh_frequency_values_are_controlled():
    rows = build_alignment()
    for row in rows:
        assert row["refresh_frequency"] in ALLOWED_REFRESH


def test_required_sources_have_min_rows_thresholds_and_outputs():
    rows = build_alignment()
    required_rows = [row for row in rows if row["required"]]
    assert required_rows
    for row in required_rows:
        assert row["has_expected_outputs"]
        assert row["has_validation_threshold"]


def test_manual_exports_have_drop_dirs():
    rows = build_alignment()
    for row in rows:
        if row["authentication"] == "manual_export":
            assert row["manual_drop_dir"]


def test_api_key_auth_format_has_env_var():
    rows = build_alignment()
    for row in rows:
        auth = row["authentication"]
        if auth.startswith("api_key:"):
            assert auth.split(":", 1)[1].strip()


def test_expected_auth_manual_and_review_sources_are_warnings_not_errors():
    rows = build_alignment()
    warning_rows = [
        row
        for row in rows
        if row["blocker_type"] in {"auth_required", "manual_required", "manual_review_required"}
    ]
    assert warning_rows
    for row in warning_rows:
        assert row["alignment_status"] == "warning"


def test_operator_review_sources_are_flagged():
    rows = build_alignment()
    flagged = {row["source_id"] for row in rows if row["blocker_type"] == "manual_review_required"}
    assert OPERATOR_REVIEW_REQUIRED <= flagged


def test_alignment_report_writes_csv_and_markdown(tmp_path):
    rows = build_alignment()
    csv_path = tmp_path / "alignment.csv"
    md_path = tmp_path / "alignment.md"

    write_csv(rows, csv_path)
    write_markdown(rows, md_path)

    assert csv_path.exists()
    assert md_path.exists()
    assert "source_id" in csv_path.read_text(encoding="utf-8")
    assert "# Source Registry Top-Form Alignment" in md_path.read_text(encoding="utf-8")


def test_inference_helpers_cover_core_cases(tmp_path):
    manual = {
        "source_id": "manual",
        "authentication": "manual_export",
        "producer_script": "scripts/example.py",
        "update_cadence": "ad_hoc",
        "expected_outputs": ["out.csv"],
        "validation_threshold": {"min_rows": 1},
    }
    api_key = {
        "source_id": "sam",
        "authentication": "api_key:SAM_API_KEY",
        "producer_script": "scripts/example.py",
        "update_cadence": "monthly",
        "expected_outputs": ["out.csv"],
        "validation_threshold": {"min_rows": 1},
    }

    assert infer_intake_mode(manual) == "manual_export"
    assert infer_intake_mode(api_key) == "api_key"
    assert infer_refresh_frequency(api_key) == "monthly"
    assert infer_refresh_frequency({"update_cadence": "weird"}) == "unknown"
    assert infer_blocker_type(tmp_path, manual) == "manual_required"


def test_default_report_paths_are_under_reports():
    assert CSV_REPORT.parts[-2:] == ("reports", "source_registry_top_form_alignment.csv")
    assert MD_REPORT.parts[-2:] == ("reports", "source_registry_top_form_alignment.md")
