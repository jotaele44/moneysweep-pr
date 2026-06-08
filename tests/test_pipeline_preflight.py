"""Tests for the registry readiness preflight (scripts/pipeline_preflight.py).

Hermetic: no network calls, no producer execution, no file writes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from contract_sweeper.runtime.source_registry import all_sources
from scripts.pipeline_preflight import (
    STRUCTURAL_STATUSES,
    classify_source_readiness,
    run_pipeline_preflight,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _logger() -> logging.Logger:
    lg = logging.getLogger("test_pipeline_preflight")
    lg.setLevel(logging.DEBUG)
    return lg


def test_api_key_status_reports_present_and_missing(monkeypatch, caplog):
    """Every api_key source reports OK/MISSING; key values are never logged."""
    secret = "DUMMY_SECRET_VALUE_DO_NOT_LOG"
    monkeypatch.setenv("SAM_API_KEY", secret)
    monkeypatch.delenv("FEC_API_KEY", raising=False)

    with caplog.at_level(logging.DEBUG):
        result = run_pipeline_preflight(REPO_ROOT, _logger(), strict=False)

    text = caplog.text
    assert "sam_entities" in text
    assert "fec" in text
    assert "[OK]" in text
    assert "[MISSING]" in text
    # The key value itself must never reach the logs.
    assert secret not in text

    missing_ids = {m["source_id"] for m in result["missing_keys"]}
    assert "fec" in missing_ids
    assert "sam_entities" not in missing_ids


def test_preflight_covers_every_registry_source():
    """100% coverage: every registry source is inspected exactly once."""
    result = run_pipeline_preflight(REPO_ROOT, _logger(), strict=False)
    sources = all_sources(REPO_ROOT)

    assert result["total_sources"] == len(sources)
    assert result["checked_sources"] == result["total_sources"]

    detail_ids = [d["source_id"] for d in result["details"]]
    assert len(detail_ids) == len(set(detail_ids))  # each appears exactly once
    assert sorted(detail_ids) == sorted(s["source_id"] for s in sources)


def test_strict_fails_on_structural_error_but_nonstrict_continues(monkeypatch):
    """A structural error fails strict mode only; non-strict stays ok."""
    broken = [
        {
            "source_id": "synthetic_broken",
            "family": "test",
            "required": True,
            "authentication": "none",
            "producer_script": "archive/r4_legacy/scripts/download_grants.py",
            "expected_outputs": [],
        }
    ]
    monkeypatch.setattr(
        "contract_sweeper.runtime.source_registry.all_sources",
        lambda root=None: broken,
    )

    nonstrict = run_pipeline_preflight(REPO_ROOT, _logger(), strict=False)
    strict = run_pipeline_preflight(REPO_ROOT, _logger(), strict=True)

    assert nonstrict["ok"] is True
    assert strict["ok"] is False
    assert "synthetic_broken" in strict["structural_errors"]
    assert "synthetic_broken" in nonstrict["structural_errors"]


def test_archived_optional_is_not_structural():
    """An optional source on an archive/ path is archived_optional, not an error."""
    source = {
        "source_id": "synthetic_optional",
        "family": "test",
        "required": False,
        "authentication": "none",
        "producer_script": "archive/r4_legacy/scripts/download_fema.py",
        "expected_outputs": [],
    }
    res = classify_source_readiness(REPO_ROOT, source)
    assert res["readiness_status"] == "archived_optional"
    assert res["readiness_status"] not in STRUCTURAL_STATUSES
    assert res["issues"] == []


def test_required_archived_is_structural():
    """A required source on an archive/ path is a blocking structural error."""
    source = {
        "source_id": "synthetic_required_archived",
        "family": "test",
        "required": True,
        "authentication": "none",
        "producer_script": "archive/r4_legacy/scripts/download_fema.py",
        "expected_outputs": [],
    }
    res = classify_source_readiness(REPO_ROOT, source)
    assert res["readiness_status"] == "blocked_required_archived"
    assert res["readiness_status"] in STRUCTURAL_STATUSES
