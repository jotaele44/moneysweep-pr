"""Contract tests for the government-flow federal API producers (Tranche 1).

These producers hit live APIs, so their network paths are not exercised in CI.
These tests assert the structural contract the readiness classifier and
orchestrator rely on: a callable ``run`` and a well-formed ``OUTPUT_COLUMNS``.
The shared HTTP plumbing is covered by ``tests/test_base_downloader.py``.
"""

from __future__ import annotations

import importlib

import pytest

DOWNLOADER_MODULES = [
    "download_usaspending_loans",
    "download_usda_farm",
    "download_cdbg_mit",
    "download_fac",
    "download_sam_exclusions",
    "download_fema_ia",
    "download_opportunity_zones",
    "download_opm_fedscope",
]


def _mod(name: str):
    return importlib.import_module(f"scripts.{name}")


@pytest.mark.unit
@pytest.mark.parametrize("module", DOWNLOADER_MODULES)
def test_exposes_callable_run(module):
    assert callable(getattr(_mod(module), "run", None))


@pytest.mark.unit
@pytest.mark.parametrize("module", DOWNLOADER_MODULES)
def test_output_columns_well_formed(module):
    cols = getattr(_mod(module), "OUTPUT_COLUMNS", None)
    assert isinstance(cols, list) and cols, f"{module}: OUTPUT_COLUMNS must be a non-empty list"
    assert all(isinstance(c, str) and c for c in cols), f"{module}: column names must be strings"
    assert len(cols) == len(set(cols)), f"{module}: duplicate column names"


@pytest.mark.unit
def test_sam_exclusions_no_key_writes_empty(tmp_path, monkeypatch):
    """Without SAM_API_KEY the exclusions producer degrades to a header-only CSV."""
    monkeypatch.delenv("SAM_API_KEY", raising=False)
    mod = _mod("download_sam_exclusions")
    result = mod.run(root=tmp_path, force=True)
    assert result["status"] == "NO_KEY"
    assert result["rows"] == 0
    import pandas as pd

    out = pd.read_csv(result["path"])
    assert list(out.columns) == mod.OUTPUT_COLUMNS
