"""Smoke tests for downloader scripts wired in from archive/ (staged PRs B1-B6).

Each batch un-archives a family of optional source producers. These tests confirm
the modules import cleanly, expose a callable run(), and that the registry points
their source(s) at the live scripts/ path. They do not exercise network calls.
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.source_registry import source_by_id

# (source_id, producer module basename) — extended as each B-batch lands.
B1_FEDERAL_GRANTS = [
    ("ed_grants", "download_ed"),
    ("hhs_grants", "download_hhs"),
    ("doj_grants", "download_doj_grants"),
    ("oia_grants", "download_oia"),
    ("epa_grants", "download_epa"),
    ("dot_grants", "download_dot"),
    ("usda_grants", "download_usda"),
    ("doe_grants", "download_doe"),
    ("research_grants", "download_research"),
    ("grants_gov", "download_grants"),
    ("fpds_report_builder", "download_grants"),
]


@pytest.mark.parametrize("source_id,module", B1_FEDERAL_GRANTS)
def test_wired_producer_imports_and_runs(source_id, module):
    mod = importlib.import_module(f"scripts.{module}")
    assert callable(getattr(mod, "run", None)), f"{module}: missing callable run()"


@pytest.mark.parametrize("source_id,module", B1_FEDERAL_GRANTS)
def test_wired_registry_points_to_scripts(source_id, module):
    src = source_by_id(source_id)
    assert src is not None, f"{source_id}: not in registry"
    assert src["producer_script"] == f"scripts/{module}.py", (
        f"{source_id}: producer_script {src['producer_script']!r} not wired to scripts/"
    )
