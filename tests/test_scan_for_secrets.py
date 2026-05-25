"""Tests for scripts/scan_for_secrets.py.

Drives the scanner against synthetic repo trees built under tmp_path. No
network, no real secrets. Every "secret" string here is assembled at runtime
from harmless fragments (e.g. ``"sk-" + "rest..."``) so that no literal in
this source file matches the scanner's own regexes — otherwise the
repo-wide `test_no_secret_leakage` check would flag this file.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scan_for_secrets import main, scan


# Synthetic, runtime-assembled credential-shaped strings. Each fragment alone
# is short enough that it does NOT match the scanner's regexes; only the
# concatenated value (which lives in tmp_path test fixtures) does.
_SK = "sk-" + "realsecretvalue" + "1234567890abcdef"           # sk-* pattern
_AKIA = "AKIA" + "0123456789ABCDEF"                            # AWS access key
_GHP = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"         # GitHub PAT
_BEARER_VAL = "abcdefghijklmnopqrstuvwxyz"                     # Bearer token body


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.unit
def test_clean_tree_returns_exit_0(tmp_path):
    _write(tmp_path / "module.py", "x = 1\nprint('hello')\n")
    assert main(["--root", str(tmp_path)]) == 0


@pytest.mark.unit
def test_real_sam_api_key_in_scanned_file_is_flagged(tmp_path):
    # .env / .env.example files have empty `suffix` (Path(".env").suffix == "")
    # so the scanner skips them by design. Use a .txt file that IS scanned.
    _write(tmp_path / "secrets.txt", "SAM_API_KEY=" + _SK + "\n")
    result = scan(tmp_path)
    assert len(result["findings"]) >= 1
    assert any("SAM_API_KEY" in f["reason"] for f in result["findings"])
    assert main(["--root", str(tmp_path)]) == 3


@pytest.mark.unit
def test_placeholder_value_is_not_flagged(tmp_path):
    _write(tmp_path / "secrets.txt", "SAM_API_KEY=paste_your_key_here\n")
    result = scan(tmp_path)
    assert result["findings"] == []


@pytest.mark.unit
def test_python_assignment_with_real_key_flagged(tmp_path):
    _write(tmp_path / "config.py", 'SAM_API_KEY = "' + _SK + '"\n')
    assert main(["--root", str(tmp_path)]) == 3


@pytest.mark.unit
def test_aws_access_key_pattern_flagged(tmp_path):
    _write(tmp_path / "module.py", 'aws_key = "' + _AKIA + '"\n')
    result = scan(tmp_path)
    assert any("credential pattern" in f["reason"] for f in result["findings"])


@pytest.mark.unit
def test_sk_token_pattern_flagged(tmp_path):
    _write(tmp_path / "module.py", 'token = "' + _SK + '"\n')
    result = scan(tmp_path)
    assert any("credential pattern" in f["reason"] for f in result["findings"])


@pytest.mark.unit
def test_github_pat_pattern_flagged(tmp_path):
    _write(tmp_path / "module.py", 'gh = "' + _GHP + '"\n')
    result = scan(tmp_path)
    assert any("credential pattern" in f["reason"] for f in result["findings"])


@pytest.mark.unit
def test_bearer_token_pattern_flagged(tmp_path):
    _write(
        tmp_path / "module.py",
        'headers = {"Authorization": "Bearer ' + _BEARER_VAL + '"}\n',
    )
    result = scan(tmp_path)
    assert any("credential pattern" in f["reason"] for f in result["findings"])


@pytest.mark.unit
def test_allowlisted_tests_fixtures_path_skipped(tmp_path):
    _write(
        tmp_path / "tests" / "fixtures" / "r5" / "sample.json",
        '{"aws_access_key": "' + _AKIA + '"}\n',
    )
    result = scan(tmp_path)
    assert result["findings"] == []


@pytest.mark.unit
def test_allowlisted_data_manifests_path_skipped(tmp_path):
    sha = "a" * 64
    _write(
        tmp_path / "data" / "manifests" / "foo.json",
        '{"sha256": "' + sha + '"}\n',
    )
    result = scan(tmp_path)
    assert result["findings"] == []


@pytest.mark.unit
def test_commented_out_secret_is_not_flagged(tmp_path):
    _write(tmp_path / "module.py", "# SAM_API_KEY=" + _SK + "\n")
    result = scan(tmp_path)
    assert result["findings"] == []


@pytest.mark.unit
def test_unsupported_extension_skipped(tmp_path):
    _write(tmp_path / "blob.bin", _AKIA + "\n")
    result = scan(tmp_path)
    assert result["findings"] == []


@pytest.mark.unit
def test_json_output_format(tmp_path):
    _write(tmp_path / "secrets.txt", "SAM_API_KEY=" + _SK + "\n")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(tmp_path), "--json"])
    payload = json.loads(buf.getvalue())
    assert isinstance(payload.get("findings"), list)
    assert isinstance(payload.get("files_scanned"), int)
    assert rc == 3
