"""Tests for scripts.install_api_keys_from_zip.

Hermetic: builds a synthetic API_KEYS.zip in tmp_path, installs to a tmp .env,
and verifies content + mode. No real keys touched. No network calls.
"""
from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

import pytest

from scripts.install_api_keys_from_zip import (
    EDGE_QUOTE_CHARS,
    diagnostics,
    main,
    read_keys_from_zip,
    write_env,
)


DUMMY_SAM = "DUMMY-sam-12345678901234567890"
DUMMY_HG = "DUMMY-highergov-abcdef"
DUMMY_LDA = "DUMMY-lda-zyx"


def _build_zip(path: Path, entries: dict[str, str]) -> Path:
    """Create a zip mapping `filename -> file contents`."""
    with zipfile.ZipFile(path, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return path


def test_read_keys_and_normalize_casing(tmp_path):
    z = _build_zip(
        tmp_path / "keys.zip",
        {
            "API KEYS/SAM_API_KEY.txt": DUMMY_SAM,
            "API KEYS/HigherGOV_API_KEY.txt": DUMMY_HG,        # mixed case stem
            "API KEYS/LDA_API_KEY.txt": DUMMY_LDA,
            "__MACOSX/API KEYS/._SAM_API_KEY.txt": "<macos-resource-fork>",
            "API KEYS/README.txt": "not a key",                  # ignored
        },
    )
    keys = read_keys_from_zip(z)
    assert keys == {
        "SAM_API_KEY": DUMMY_SAM,
        "HIGHERGOV_API_KEY": DUMMY_HG,  # canonical name, mixed-case stem normalized
        "LDA_API_KEY": DUMMY_LDA,
    }


def test_edge_quotes_and_whitespace_stripped(tmp_path):
    # Smart-quote-wrapped value, surrounded by whitespace and a newline.
    wrapped = f"  “{DUMMY_HG}”  \n"
    z = _build_zip(tmp_path / "keys.zip", {"HIGHERGOV_API_KEY.txt": wrapped})
    keys = read_keys_from_zip(z)
    assert keys["HIGHERGOV_API_KEY"] == DUMMY_HG
    assert all(ord(c) < 128 for c in keys["HIGHERGOV_API_KEY"])
    # Sanity: the stripper covers smart quotes too.
    assert "“" in EDGE_QUOTE_CHARS and "”" in EDGE_QUOTE_CHARS


def test_write_env_mode_and_content(tmp_path):
    env_path = tmp_path / ".env"
    keys = {"SAM_API_KEY": DUMMY_SAM, "LDA_API_KEY": DUMMY_LDA}
    n = write_env(keys, env_path, force=False)
    assert n == 2
    # mode 0600
    mode = stat.S_IMODE(env_path.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
    body = env_path.read_text(encoding="utf-8")
    assert f"SAM_API_KEY={DUMMY_SAM}" in body
    assert f"LDA_API_KEY={DUMMY_LDA}" in body
    assert body.startswith("# Generated"), "missing header comment"


def test_write_env_refuses_overwrite_without_force(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=keepme\n")
    with pytest.raises(FileExistsError):
        write_env({"SAM_API_KEY": DUMMY_SAM}, env_path, force=False)
    # File untouched
    assert env_path.read_text() == "EXISTING=keepme\n"


def test_write_env_overwrites_with_force(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=keepme\n")
    write_env({"SAM_API_KEY": DUMMY_SAM}, env_path, force=True)
    assert "EXISTING=keepme" not in env_path.read_text()
    assert f"SAM_API_KEY={DUMMY_SAM}" in env_path.read_text()


def test_diagnostics_never_prints_values():
    """The diagnostics summary must not contain any key value."""
    keys = {"SAM_API_KEY": DUMMY_SAM, "HIGHERGOV_API_KEY": DUMMY_HG}
    for line in diagnostics(keys):
        assert DUMMY_SAM not in line
        assert DUMMY_HG not in line
        assert "len=" in line and "non_ascii=" in line


def test_main_end_to_end(tmp_path, capsys):
    z = _build_zip(
        tmp_path / "keys.zip",
        {
            "SAM_API_KEY.txt": DUMMY_SAM,
            "LDA_API_KEY.txt": DUMMY_LDA,
        },
    )
    env_path = tmp_path / ".env"
    rc = main(["--zip", str(z), "--env", str(env_path)])
    assert rc == 0
    captured = capsys.readouterr()
    # Values must not leak to stdout, even from the summary path.
    assert DUMMY_SAM not in captured.out
    assert DUMMY_LDA not in captured.out
    # But .env on disk contains them verbatim.
    body = env_path.read_text(encoding="utf-8")
    assert DUMMY_SAM in body and DUMMY_LDA in body


def test_main_returns_nonzero_for_missing_zip(tmp_path):
    rc = main(["--zip", str(tmp_path / "nope.zip")])
    assert rc == 2


def test_main_returns_nonzero_for_empty_zip(tmp_path):
    z = _build_zip(tmp_path / "empty.zip", {"README.txt": "no keys here"})
    rc = main(["--zip", str(z), "--env", str(tmp_path / ".env")])
    assert rc == 3
