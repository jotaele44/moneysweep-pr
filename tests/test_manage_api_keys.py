"""Tests for scripts/manage_api_keys.py — the read/write layer shared by
scripts/set_api_key.py (CLI) and server/backend/api_keys.py (dashboard).

All operations are pointed at tmp_path via explicit env_path/example_path
arguments; the real repo .env is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.manage_api_keys import InvalidKeyValueError, known_keys, key_status, set_key

REAL_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _expected_key_count() -> int:
    return len(known_keys(REAL_EXAMPLE))


def test_known_keys_parses_all_real_vars_with_expected_required_flags():
    parsed_keys = known_keys(REAL_EXAMPLE)
    keys = {k.name: k for k in parsed_keys}
    assert len(keys) == len(parsed_keys)

    for required_name in (
        "SAM_API_KEY",
        "LDA_API_KEY",
        "FAC_API_KEY",
        "EIA_API_KEY",
        "FRED_API_KEY",
        "OPENSTATES_API_KEY",
    ):
        assert keys[required_name].required is True, required_name

    for optional_name in (
        "FEC_API_KEY",
        "HIGHERGOV_API_KEY",
        "DATA_GOV_API_KEY",
        "CENSUS_API_KEY",
        "FELT_API_KEY",
        "FINANCIALDATA_API_KEY",
        "FINANCIALDATA_LICENSE_APPROVED",
        "X_API_KEY",
        "PROPUBLICA_API_KEY",
        "CMS_APP_TOKEN",
        "SOCRATA_APP_TOKEN",
    ):
        assert keys[optional_name].required is False, optional_name

    # Every key gets a non-empty description from its comment block.
    assert all(k.description for k in keys.values())


def test_known_keys_empty_when_example_missing(tmp_path):
    assert known_keys(tmp_path / "does-not-exist.example") == []


def test_set_key_rejects_unknown_name(tmp_path):
    env = tmp_path / ".env"
    with pytest.raises(ValueError, match="unknown key"):
        set_key("NOT_A_REAL_KEY", "value", env_path=env, example_path=REAL_EXAMPLE)
    assert not env.exists()


@pytest.mark.parametrize("name", ["MONEYSWEEP_CORS_ORIGINS", "MONEYSWEEP_CASE_DB"])
def test_set_key_rejects_noncredential_configuration(tmp_path, name):
    env = tmp_path / ".env"
    with pytest.raises(ValueError, match="unknown key"):
        set_key(name, "unsafe-remote-override", env_path=env, example_path=REAL_EXAMPLE)
    assert not env.exists()


@pytest.mark.parametrize("value", ["", "   ", "first\nSECOND=value", "x\r\ny", "x\0y"])
def test_set_key_rejects_unsafe_values(tmp_path, value):
    env = tmp_path / ".env"
    with pytest.raises(InvalidKeyValueError):
        set_key("SAM_API_KEY", value, env_path=env, example_path=REAL_EXAMPLE)
    assert not env.exists()


def test_set_key_seeds_env_from_example_when_missing(tmp_path):
    env = tmp_path / ".env"
    assert not env.exists()

    set_key("SAM_API_KEY", "sk-real-value", env_path=env, example_path=REAL_EXAMPLE)

    assert env.exists()
    status = {row["name"]: row for row in key_status(env_path=env, example_path=REAL_EXAMPLE)}
    assert status["SAM_API_KEY"]["is_set"] is True
    # Every other var was seeded from .env.example's own placeholder, which
    # must never count as a real value.
    assert status["FEC_API_KEY"]["is_set"] is False
    assert status["OPENSTATES_API_KEY"]["is_set"] is False


def test_set_key_updates_in_place_preserving_other_lines(tmp_path):
    env = tmp_path / ".env"
    set_key("SAM_API_KEY", "first-value", env_path=env, example_path=REAL_EXAMPLE)
    line_count_before = len(env.read_text().splitlines())

    set_key("SAM_API_KEY", "second-value", env_path=env, example_path=REAL_EXAMPLE)

    lines = env.read_text().splitlines()
    sam_lines = [line for line in lines if line.startswith("SAM_API_KEY=")]
    assert sam_lines == ["SAM_API_KEY=second-value"]
    assert len(lines) == line_count_before


def test_set_key_appends_when_absent_from_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SOME_OTHER_LINE=1\n", encoding="utf-8")

    set_key("CENSUS_API_KEY", "census-value", env_path=env, example_path=REAL_EXAMPLE)

    lines = env.read_text().splitlines()
    assert "SOME_OTHER_LINE=1" in lines
    assert "CENSUS_API_KEY=census-value" in lines


def test_key_status_never_includes_a_value_field(tmp_path):
    env = tmp_path / ".env"
    set_key("SAM_API_KEY", "a-secret-nobody-should-see", env_path=env, example_path=REAL_EXAMPLE)

    status = key_status(env_path=env, example_path=REAL_EXAMPLE)
    for row in status:
        assert set(row.keys()) == {"name", "description", "required", "is_set"}
        assert "a-secret-nobody-should-see" not in str(row)


def test_key_status_missing_env_reports_everything_unset(tmp_path):
    status = key_status(env_path=tmp_path / "nope.env", example_path=REAL_EXAMPLE)
    expected_names = {key.name for key in known_keys(REAL_EXAMPLE)}
    assert len(status) == _expected_key_count()
    assert {row["name"] for row in status} == expected_names
    assert all(row["is_set"] is False for row in status)
