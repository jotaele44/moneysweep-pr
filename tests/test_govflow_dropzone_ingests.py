"""Behavior tests for the government-flow dropzone readers (Tranches 2-3).

All 17 readers delegate to ``moneysweep.runtime.dropzone_ingest`` and are
network-free, so they are exercised directly here: empty-dropzone handling, the
shared Spanish/English column mapping with blank-key filtering, and the cached
short-circuit.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

# (module, raw_dir leaf, a header→value sample keyed by the module's KEY_FIELD)
INGEST_MODULES = [
    "ingest_ocpr_contracts",
    "ingest_doj_settlements",
    "ingest_equitable_sharing",
    "ingest_irs_ctc_eitc_pr",
    "ingest_ddec_incentives",
    "ingest_crim_property_tax",
    "ingest_ases_plan_vital",
    "ingest_loteria_pr",
    "ingest_gaming_commission",
    "ingest_ports_authority",
    "ingest_act_tolls_concession",
    "ingest_oatrh_payroll",
    "ingest_ogpe_permits",
    "ingest_dtop_vehicle_fees",
    "ingest_tourism_room_tax",
    "ingest_bde_loans",
    "ingest_prpha_housing_subsidy",
]


def _mod(name: str):
    return importlib.import_module(f"scripts.{name}")


@pytest.mark.unit
@pytest.mark.parametrize("module", INGEST_MODULES)
def test_no_raw_dir_writes_empty_header(module, tmp_path):
    mod = _mod(module)
    result = mod.run(root=tmp_path, force=True)
    assert result["status"] == "NO_FILES"
    out = pd.read_csv(Path(result["path"]))
    assert list(out.columns) == mod.OUTPUT_COLUMNS
    assert "source_file" in mod.OUTPUT_COLUMNS
    assert mod.KEY_FIELD in mod.OUTPUT_COLUMNS
    assert len(out) == 0


@pytest.mark.unit
@pytest.mark.parametrize("module", INGEST_MODULES)
def test_blank_key_rows_filtered_and_mapped(module, tmp_path):
    """A row with a populated key field survives; a blank-key row is dropped."""
    mod = _mod(module)
    raw = tmp_path / mod.RAW_DIR_NAME
    raw.mkdir(parents=True)

    # Build a raw frame using the first candidate header for every mapped field.
    good = {candidates[0]: f"val_{target}" for target, candidates in mod.COL_MAP.items()}
    blank = dict(good)
    # Blank out the key field's source column so the row is filtered.
    key_first_header = mod.COL_MAP[mod.KEY_FIELD][0]
    blank[key_first_header] = ""
    pd.DataFrame([good, blank]).to_csv(raw / "sample.csv", index=False)

    result = mod.run(root=tmp_path, force=True)
    assert result["status"] == "OK"
    assert result["rows"] == 1
    out = pd.read_csv(Path(result["path"]), dtype=str)
    assert out.iloc[0][mod.KEY_FIELD] == f"val_{mod.KEY_FIELD}"
    assert out.iloc[0]["source_file"] == "sample.csv"


@pytest.mark.unit
@pytest.mark.parametrize("module", INGEST_MODULES)
def test_cached_output_short_circuits(module, tmp_path):
    mod = _mod(module)
    out_path = tmp_path / mod.OUTPUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    row = {c: ("X" if c == mod.KEY_FIELD else "") for c in mod.OUTPUT_COLUMNS}
    pd.DataFrame([row]).to_csv(out_path, index=False)
    result = mod.run(root=tmp_path, force=False)
    assert result["status"] == "CACHED"
    assert result["rows"] == 1
