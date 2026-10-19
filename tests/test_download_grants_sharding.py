from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from scripts import download_grants


def _write_raw(path: Path, *, award_id: str = "AWARD-1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {column: "" for column in download_grants.MASTER_COLUMNS}
    row["award_id"] = award_id
    pd.DataFrame([row], columns=download_grants.MASTER_COLUMNS).to_csv(path, index=False)


def test_fiscal_year_windows_are_exact_and_inclusive() -> None:
    assert download_grants._fy_windows(2024, 2025) == [
        {
            "label": "2024",
            "start_date": "2023-10-01",
            "end_date": "2024-09-30",
        },
        {
            "label": "2025",
            "start_date": "2024-10-01",
            "end_date": "2025-09-30",
        },
    ]


def test_cached_file_requires_the_exact_generated_schema(tmp_path: Path) -> None:
    valid = tmp_path / "valid.csv"
    invalid = tmp_path / "invalid.csv"
    _write_raw(valid)
    invalid.write_text("award_id\nAWARD-1\n", encoding="utf-8")

    assert download_grants._file_has_data(valid) is True
    assert download_grants._file_has_data(invalid) is False


def test_server_errors_are_retried_before_submission_fails(monkeypatch) -> None:
    session = MagicMock()
    responses = []
    for status in (500, 502):
        response = MagicMock(status_code=status, text="blocked")
        response.raise_for_status.side_effect = download_grants.requests.HTTPError(str(status))
        responses.append(response)
    success = MagicMock(status_code=200)
    success.raise_for_status.return_value = None
    success.json.return_value = {"status": "finished", "file_url": "https://example.test/a.zip"}
    responses.append(success)
    session.post.side_effect = responses
    sleep = MagicMock()
    monkeypatch.setattr(download_grants.time, "sleep", sleep)

    result = download_grants._submit_bulk_job(session, {}, MagicMock())

    assert result == {"status": "finished", "file_url": "https://example.test/a.zip"}
    assert session.post.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [30, 60]


def test_download_pass_tracks_only_real_api_calls(monkeypatch, tmp_path: Path) -> None:
    outcomes = {
        "2024": {"fy": "2024", "rows": 3, "error": None, "skipped": True},
        "2025": {"fy": "2025", "rows": 4, "error": None, "skipped": False},
    }
    monkeypatch.setattr(
        download_grants,
        "_run_one_window",
        lambda _session, _prefix, _types, _filter, window, _raw, _force, _logger: outcomes[
            window["label"]
        ],
    )
    sleep = MagicMock()
    monkeypatch.setattr(download_grants.time, "sleep", sleep)

    stats = download_grants.download_pass(
        MagicMock(),
        "grants_pop",
        ["02"],
        "pop",
        tmp_path,
        False,
        MagicMock(),
        fy_start=2024,
        fy_end=2025,
    )

    assert stats == {"prefix": "grants_pop", "rows": 7, "errors": [], "api_calls": 1}
    sleep.assert_not_called()


def test_shard_run_emits_exact_manifest_without_master(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(download_grants, "_session", MagicMock)
    monkeypatch.setattr(download_grants.time, "sleep", MagicMock())

    def fake_window(
        _session,
        prefix,
        _types,
        _filter,
        window,
        raw_dir,
        _force,
        _logger,
    ):
        _write_raw(raw_dir / f"{prefix}_fy{window['label']}.csv", award_id=window["label"])
        return {"fy": window["label"], "rows": 1, "error": None, "skipped": False}

    monkeypatch.setattr(download_grants, "_run_one_window", fake_window)
    summary = download_grants._run(
        root=tmp_path,
        only_pass="grants_pop",
        fy_start=2024,
        fy_end=2025,
        build_master_output=False,
    )

    assert summary["schema_version"] == "moneysweep.grants_download/v2"
    assert summary["master_built"] is False
    assert summary["errors"] == []
    assert summary["expected_raw_files"] == [
        "data/staging/raw/grants/grants_pop_fy2024.csv",
        "data/staging/raw/grants/grants_pop_fy2025.csv",
    ]
    assert len(summary["raw_files"]) == 2
    assert all(
        record["columns"] == download_grants.MASTER_COLUMNS for record in summary["raw_files"]
    )
    assert not (tmp_path / "data/staging/processed/pr_grants_master.csv").exists()


def test_cached_full_run_builds_one_master_without_interpass_sleep(
    monkeypatch, tmp_path: Path
) -> None:
    for index, (prefix, _, _) in enumerate(download_grants.PASSES):
        _write_raw(
            tmp_path / f"data/staging/raw/grants/{prefix}_fy2024.csv",
            award_id=f"AWARD-{index}",
        )
    session = MagicMock()
    monkeypatch.setattr(download_grants, "_session", lambda: session)
    sleep = MagicMock()
    monkeypatch.setattr(download_grants.time, "sleep", sleep)

    summary = download_grants._run(root=tmp_path, fy_start=2024, fy_end=2024)

    assert summary["errors"] == []
    assert summary["master_built"] is True
    assert summary["master_rows"] == 4
    assert len(summary["raw_files"]) == 4
    sleep.assert_not_called()
    session.close.assert_called_once_with()


def test_master_preserves_rows_without_stable_award_ids(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    first = raw_dir / "first.csv"
    second = raw_dir / "second.csv"
    _write_raw(first, award_id="")
    _write_raw(second, award_id="")
    master = tmp_path / "master.csv"

    rows = download_grants.build_master(
        raw_dir,
        master,
        MagicMock(),
        files=[first, second],
    )

    assert rows == 2
    assert len(pd.read_csv(master, dtype=str)) == 2


def test_master_build_failure_does_not_replace_existing_snapshot(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    invalid = raw_dir / "invalid.csv"
    invalid.parent.mkdir(parents=True)
    invalid.write_bytes(b"\xff")
    master = tmp_path / "master.csv"
    master.write_text("preserved\n", encoding="utf-8")

    try:
        download_grants.build_master(
            raw_dir,
            master,
            MagicMock(),
            files=[invalid],
        )
    except RuntimeError as exc:
        assert "cannot build grants master" in str(exc)
    else:
        raise AssertionError("malformed raw input was accepted")

    assert master.read_text(encoding="utf-8") == "preserved\n"


def test_environment_fiscal_years_freeze_finalization_snapshot(monkeypatch) -> None:
    monkeypatch.setenv("MONEYSWEEP_GRANTS_START_FY", "2000")
    monkeypatch.setenv("MONEYSWEEP_GRANTS_END_FY", "2027")

    assert download_grants._environment_fiscal_year("MONEYSWEEP_GRANTS_START_FY") == 2000
    assert download_grants._environment_fiscal_year("MONEYSWEEP_GRANTS_END_FY") == 2027

    monkeypatch.setenv("MONEYSWEEP_GRANTS_END_FY", "not-a-year")
    try:
        download_grants._environment_fiscal_year("MONEYSWEEP_GRANTS_END_FY")
    except ValueError as exc:
        assert "must be an integer" in str(exc)
    else:
        raise AssertionError("invalid fiscal-year environment value was accepted")


def test_missing_raw_output_prevents_partial_master(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(download_grants, "_session", MagicMock)
    monkeypatch.setattr(
        download_grants,
        "_run_one_window",
        lambda _session, _prefix, _types, _filter, window, _raw, _force, _logger: {
            "fy": window["label"],
            "rows": 0,
            "error": "upstream blocked",
            "skipped": False,
        },
    )

    summary = download_grants._run(
        root=tmp_path,
        only_pass="grants_pop",
        fy_start=2024,
        fy_end=2024,
    )

    assert summary["master_built"] is False
    assert any("upstream blocked" in error for error in summary["errors"])
    assert any(error.startswith("missing raw output:") for error in summary["errors"])
    assert not (tmp_path / "data/staging/processed/pr_grants_master.csv").exists()


def test_invalid_range_summary_is_complete_and_serializable(tmp_path: Path) -> None:
    summary = download_grants._run(root=tmp_path, fy_start=2025, fy_end=2024)

    assert summary["master_built"] is False
    assert summary["raw_files"] == []
    json.dumps(summary)


def test_zip_without_csv_is_an_error_not_valid_empty_data(tmp_path: Path) -> None:
    archive = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("readme.txt", "not a dataset")

    frame, error = download_grants._extract_csv(archive, MagicMock())

    assert frame.empty
    assert error == "no CSV files found in invalid.zip"
