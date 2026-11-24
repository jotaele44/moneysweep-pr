from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.build_keyless_source_evidence import build_source_evidence


SHA = "a" * 40


def _fixture_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    output = root / "data/staging/processed/fixture.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("id,value\n1,alpha\n", encoding="utf-8")
    registry = root / "registries/source_registry.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        """
sources:
  - source_id: fixture
    required: false
    family: test
    authentication: none
    endpoint_url: https://example.test/api
    producer_script: scripts/fixture.py
    expected_outputs:
      - data/staging/processed/fixture.csv
""".lstrip(),
        encoding="utf-8",
    )
    return root, output


def test_success_emits_standardized_receipt_and_copied_bytes(tmp_path: Path) -> None:
    root, source_output = _fixture_root(tmp_path)
    receipt = build_source_evidence(
        root=root,
        source_id="fixture",
        step_outcome="success",
        scope_sha="b" * 40,
        implementation_sha=SHA,
        output_root=Path("certification_out"),
    )

    out = root / "certification_out/fixture"
    copied = out / "files/data/staging/processed/fixture.csv"
    assert receipt["standardized_receipt_emitted"] is True
    assert receipt["missing_expected_outputs"] == []
    assert copied.read_bytes() == source_output.read_bytes()
    standardized = json.loads((out / "operator_evidence/fixture.json").read_text(encoding="utf-8"))
    assert standardized["acquisition"]["source_url"] == "https://example.test/api"


def test_failed_execution_preserves_file_but_emits_no_acquisition_receipt(
    tmp_path: Path,
) -> None:
    root, _ = _fixture_root(tmp_path)
    receipt = build_source_evidence(
        root=root,
        source_id="fixture",
        step_outcome="failure",
        scope_sha="b" * 40,
        implementation_sha=SHA,
        output_root=Path("certification_out"),
    )

    out = root / "certification_out/fixture"
    assert receipt["standardized_receipt_emitted"] is False
    assert receipt["standardized_receipt_error"] == (
        "execution_not_successful_no_acquisition_receipt"
    )
    assert (out / "files/data/staging/processed/fixture.csv").is_file()
    assert not (out / "operator_evidence/fixture.json").exists()


def test_rerun_clears_stale_success_receipt_and_records_missing_output(
    tmp_path: Path,
) -> None:
    root, source_output = _fixture_root(tmp_path)
    kwargs = {
        "root": root,
        "source_id": "fixture",
        "scope_sha": "b" * 40,
        "implementation_sha": SHA,
        "output_root": Path("certification_out"),
    }
    build_source_evidence(step_outcome="success", **kwargs)
    source_output.unlink()

    receipt = build_source_evidence(step_outcome="success", **kwargs)

    out = root / "certification_out/fixture"
    assert receipt["missing_expected_outputs"] == ["data/staging/processed/fixture.csv"]
    assert receipt["standardized_receipt_error"] == (
        "missing_expected_outputs_no_acquisition_receipt"
    )
    assert not (out / "operator_evidence/fixture.json").exists()


def test_corrupt_runner_summary_is_reported_without_losing_evidence(tmp_path: Path) -> None:
    root, _ = _fixture_root(tmp_path)
    runner = root / "data/staging/materialization_run_summary.json"
    runner.write_text("{not-json", encoding="utf-8")

    receipt = build_source_evidence(
        root=root,
        source_id="fixture",
        step_outcome="success",
        scope_sha="b" * 40,
        implementation_sha=SHA,
        output_root=Path("certification_out"),
    )

    assert receipt["runner_summary"] is None
    assert receipt["runner_summary_error"].startswith("JSONDecodeError:")


def test_unknown_source_is_rejected(tmp_path: Path) -> None:
    root, _ = _fixture_root(tmp_path)

    with pytest.raises(ValueError, match="unknown source_id"):
        build_source_evidence(
            root=root,
            source_id="unknown",
            step_outcome="success",
            scope_sha="b" * 40,
            implementation_sha=SHA,
            output_root=Path("certification_out"),
        )
