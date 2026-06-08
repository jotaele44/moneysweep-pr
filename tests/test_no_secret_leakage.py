"""Tests that no secrets are committed to the repo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "scripts" / "scan_for_secrets.py"


@pytest.mark.unit
@pytest.mark.pipeline_gate
def test_scan_for_secrets_exits_clean():
    """The repo must contain zero detected secrets."""
    assert SCANNER.exists(), "scripts/scan_for_secrets.py is required for this gate"
    proc = subprocess.run(
        [sys.executable, str(SCANNER), "--root", str(REPO_ROOT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    # Exit code 0 = clean, 3 = leaks. We require 0.
    assert proc.returncode == 0, (
        f"scan_for_secrets exit={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )


@pytest.mark.unit
def test_env_example_has_no_real_values():
    """`.env.example` is allowed to contain placeholders only."""
    env_example = REPO_ROOT / ".env.example"
    assert env_example.exists()
    text = env_example.read_text(encoding="utf-8")
    forbidden_starts = ("SAM_API_KEY=sam-", "LDA_API_KEY=lda-", "FEC_API_KEY=fec-")
    for prefix in forbidden_starts:
        assert prefix not in text, (
            f".env.example contains a non-placeholder value (matched: {prefix!r})"
        )


@pytest.mark.unit
def test_gitignore_excludes_dotenv():
    gi = REPO_ROOT / ".gitignore"
    assert gi.exists()
    content = gi.read_text(encoding="utf-8")
    assert ".env" in content, ".gitignore must include .env"
