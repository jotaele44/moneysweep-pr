"""Tests for the canonical pipeline entry point (scripts/pipeline.py)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PIPELINE = str(Path(__file__).resolve().parent.parent / "scripts" / "pipeline.py")


@pytest.mark.unit
def test_pipeline_help_exits_0():
    result = subprocess.run(
        [sys.executable, PIPELINE, "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "validate" in result.stdout
    assert "build" in result.stdout
    assert "signals" in result.stdout
    assert "report" in result.stdout
    assert "status" in result.stdout


@pytest.mark.unit
def test_pipeline_unknown_step_exits_nonzero():
    result = subprocess.run(
        [sys.executable, PIPELINE, "nonexistent_step"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


@pytest.mark.unit
def test_pipeline_status_exits_0(tmp_path):
    result = subprocess.run(
        [sys.executable, PIPELINE, "status"],
        capture_output=True,
        text=True,
        cwd=str(Path(PIPELINE).parent.parent),
    )
    assert result.returncode == 0


@pytest.mark.unit
def test_pipeline_module_importable():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pipeline", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
    assert callable(mod.run_step)
    assert callable(mod.run_all)
    assert "validate" in mod._STEPS
    assert "build" in mod._STEPS
    assert "signals" in mod._STEPS
    assert "report" in mod._STEPS
