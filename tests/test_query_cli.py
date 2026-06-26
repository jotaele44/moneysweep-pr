"""Tests for the ``python -m moneysweep.query`` CLI."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from moneysweep.query import Query
from moneysweep.query.cli import _build_query, _build_parser, main
from moneysweep.query.adapters import ADAPTER_REGISTRY
from moneysweep.query.adapters.base import SourceAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path):
    """Mirror the fixture used by test_query_dispatcher so cache + registry resolve under tmp_path."""
    ref_dir = tmp_path / "data" / "reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "pr_municipalities.csv").write_bytes(
        (REPO_ROOT / "data" / "reference" / "pr_municipalities.csv").read_bytes()
    )
    reg_dir = tmp_path / "registries"
    reg_dir.mkdir()
    for f in ("source_registry.json", "schema_registry.json"):
        (reg_dir / f).write_bytes((REPO_ROOT / "registries" / f).read_bytes())
    yield tmp_path


class _StaticAdapter(SourceAdapter):
    source_id = "usaspending_prime"

    def fetch(self, q: Query) -> pd.DataFrame:
        return pd.DataFrame({"municipality": ["San Juan"], "amount": ["100"]})


def _run(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


@pytest.mark.unit
def test_list_adapters_prints_registered_source_ids_and_exits_zero():
    code, stdout, _ = _run(["--list-adapters"])
    assert code == 0
    printed = set(stdout.split())
    assert printed == set(ADAPTER_REGISTRY.keys())


@pytest.mark.unit
def test_repeated_and_csv_municipality_flags_produce_same_query():
    parser = _build_parser()
    q1 = _build_query(parser.parse_args(["--municipality", "San Juan", "--municipality", "Ponce"]))
    q2 = _build_query(parser.parse_args(["--municipalities", "San Juan,Ponce"]))
    assert q1.municipalities == q2.municipalities == ("San Juan", "Ponce")


@pytest.mark.unit
def test_fiscal_years_are_parsed_as_ints():
    parser = _build_parser()
    q = _build_query(parser.parse_args(["--fy", "2023", "--fiscal-years", "2024,2025"]))
    assert q.fiscal_years == (2023, 2024, 2025)


@pytest.mark.unit
def test_date_range_passes_through():
    parser = _build_parser()
    q = _build_query(parser.parse_args(["--date-range", "2023-01-01", "2023-12-31"]))
    assert q.date_range == ("2023-01-01", "2023-12-31")


@pytest.mark.unit
def test_manual_only_source_exits_zero_and_includes_outcome(tmp_path):
    code, stdout, _ = _run(["--source", "sam_entities", "--root", str(tmp_path)])
    assert code == 0
    payload = json.loads(stdout)
    assert payload["manual_only"] == 1
    assert payload["outcomes"][0]["source_id"] == "sam_entities"
    assert payload["outcomes"][0]["status"] == "manual_only"


@pytest.mark.unit
def test_quiet_suppresses_stdout(tmp_path):
    code, stdout, _ = _run(["--source", "sam_entities", "--root", str(tmp_path), "--quiet"])
    assert code == 0
    assert stdout == ""


@pytest.mark.unit
@pytest.mark.parametrize("ext", ["parquet", "csv", "json", "jsonl"])
def test_output_writes_combined_file_for_each_supported_format(tmp_path, ext):
    out_path = tmp_path / f"results.{ext}"
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        code, _, _ = _run(
            [
                "--source",
                "usaspending_prime",
                "--municipality",
                "San Juan",
                "--root",
                str(tmp_path),
                "--output",
                str(out_path),
                "--quiet",
            ]
        )
    assert code == 0
    assert out_path.exists() and out_path.stat().st_size > 0
    if ext == "parquet":
        df = pd.read_parquet(out_path)
    elif ext == "csv":
        df = pd.read_csv(out_path)
    elif ext == "json":
        df = pd.read_json(out_path)
    else:
        df = pd.read_json(out_path, lines=True)
    assert "source_id" in df.columns
    assert (df["source_id"] == "usaspending_prime").all()


@pytest.mark.unit
def test_output_dir_writes_per_source_files(tmp_path):
    out_dir = tmp_path / "by_source"
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        code, _, _ = _run(
            [
                "--source",
                "usaspending_prime",
                "--municipality",
                "San Juan",
                "--root",
                str(tmp_path),
                "--output-dir",
                str(out_dir),
                "--format",
                "csv",
                "--quiet",
            ]
        )
    assert code == 0
    written = list(out_dir.glob("*.csv"))
    assert [p.name for p in written] == ["usaspending_prime.csv"]


@pytest.mark.unit
def test_output_dir_skips_manual_only_outcomes(tmp_path):
    out_dir = tmp_path / "by_source"
    code, _, _ = _run(
        [
            "--source",
            "sam_entities",
            "--root",
            str(tmp_path),
            "--output-dir",
            str(out_dir),
            "--quiet",
        ]
    )
    assert code == 0
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


@pytest.mark.unit
def test_unsupported_output_extension_returns_exit_code_one(tmp_path):
    out_path = tmp_path / "results.xlsx"
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        code, _, stderr = _run(
            [
                "--source",
                "usaspending_prime",
                "--municipality",
                "San Juan",
                "--root",
                str(tmp_path),
                "--output",
                str(out_path),
                "--quiet",
            ]
        )
    assert code == 1
    assert "unsupported output extension" in stderr


@pytest.mark.unit
def test_adapter_error_exits_one(tmp_path):
    class _BrokenAdapter(SourceAdapter):
        source_id = "usaspending_prime"

        def fetch(self, q):
            raise RuntimeError("upstream 500")

    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _BrokenAdapter}, clear=False):
        code, stdout, _ = _run(
            [
                "--source",
                "usaspending_prime",
                "--root",
                str(tmp_path),
                "--quiet",
            ]
        )
    assert code == 1


@pytest.mark.unit
def test_summary_payload_lists_each_outcome(tmp_path):
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        code, stdout, _ = _run(
            [
                "--source",
                "usaspending_prime",
                "--source",
                "sam_entities",
                "--municipality",
                "San Juan",
                "--root",
                str(tmp_path),
            ]
        )
    assert code == 0
    payload = json.loads(stdout)
    ids = [o["source_id"] for o in payload["outcomes"]]
    assert ids == ["usaspending_prime", "sam_entities"]
    assert payload["ok"] == 1
    assert payload["manual_only"] == 1
