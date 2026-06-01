"""Readiness gate: proves every automatable source can materialize deterministically.

This is the invariant that backs "fill all sources to 100%": the target is the
*automatable* set, and each automatable source must have a working entrypoint
(query adapter or importable producer) plus declared outputs. Non-automatable
sources must each carry an allowed *queued* reason so they are excluded from the
target on purpose, not by accident.
"""
from __future__ import annotations

import json

import pytest

from scripts.build_source_recovery_matrix import (
    OUT_JSON,
    PATH_TYPES,
    QUEUED_PATH_TYPES,
    build_rows,
    build_summary,
    main,
)

pytestmark = pytest.mark.unit

ROWS = build_rows()


def test_every_automatable_source_is_ready():
    """Automatable ⇒ (adapter or importable producer) and declared outputs."""
    not_ready = [
        r["source_id"]
        for r in ROWS
        if r["automatable"]
        and not (r["ready"] and (r["has_adapter"] or r["producer_importable"]) and r["expected_outputs_count"] > 0)
    ]
    assert not_ready == [], f"automatable sources missing a deterministic path: {not_ready}"


def test_no_broken_producers():
    """No source is stuck on an import error / missing callable / missing script."""
    broken = [r["source_id"] for r in ROWS if r["path_type"] == "broken_producer"]
    assert broken == [], f"broken producers must be repaired before fill: {broken}"


def test_non_automatable_sources_have_allowed_reason():
    """Every excluded source is queued with a documented, allowed path_type."""
    allowed = set(QUEUED_PATH_TYPES)
    bad = [
        (r["source_id"], r["path_type"])
        for r in ROWS
        if not r["automatable"] and r["path_type"] not in allowed
    ]
    assert bad == [], f"excluded sources with undocumented reason: {bad}"


def test_every_path_type_is_known():
    unknown = sorted({r["path_type"] for r in ROWS} - set(PATH_TYPES))
    assert unknown == [], f"unknown path_type(s): {unknown}"


def test_summary_counts_are_consistent():
    summary = build_summary(ROWS)
    assert summary["automatable_ready"] == summary["automatable_total"]
    assert summary["automatable_not_ready"] == []
    assert (
        summary["automatable_total"] + summary["queued_excluded_total"]
        == summary["total_sources"]
    )


def test_readiness_json_regenerates_identically():
    """Committed materialization_readiness.json is deterministic — regenerate matches."""
    committed = OUT_JSON.read_text(encoding="utf-8")
    main()  # regenerates the reports
    assert OUT_JSON.read_text(encoding="utf-8") == committed, (
        "reports/materialization_readiness.json is stale — regenerate with: "
        "python3 scripts/build_source_recovery_matrix.py"
    )


def test_committed_summary_matches_live_registry():
    """The committed readiness JSON reflects the current registry + adapters."""
    committed = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    live = build_summary(build_rows())
    assert committed == live
