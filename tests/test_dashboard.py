"""Tests for the top-form dashboard gate (Gate ``dashboard``).

Covers the source-provenance drilldown index, the analyst-reports catalog, and
the self-contained static HTML explorer. Fully offline; the producers read
committed artifacts and the schema validator is the stdlib interpreter.
"""

from __future__ import annotations

import json

import pytest

from moneysweep.validation.canonical_v1_schema import validate_row
from scripts import build_analyst_reports_manifest as bar
from scripts import build_dashboard_explorer as bde
from scripts import build_source_drilldown as bsd

REPO_ROOT = bsd.REPO_ROOT


def _schema(rel: str):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# source_drilldown
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_source_drilldown_check_and_schema():
    entries = bsd.build_entries(REPO_ROOT)
    assert bsd.check(entries, REPO_ROOT) == []
    schema = _schema(bsd.SCHEMA)
    assert entries
    for e in entries:
        assert validate_row(e, schema) == [], e
    # auto-derived from manifests -> includes artifacts from several gates
    producers = {e["producer_script"] for e in entries}
    assert "scripts/build_graph_export.py" in producers
    assert "scripts/build_foia_tracker.py" in producers
    artifacts = [e["artifact"] for e in entries]
    assert artifacts == sorted(artifacts)  # deterministic ordering


@pytest.mark.integration
def test_source_drilldown_regenerates_identically():
    built = {"sources": bsd.build_entries(REPO_ROOT)}
    on_disk = json.loads((REPO_ROOT / bsd.OUT).read_text(encoding="utf-8"))
    assert on_disk == built


# --------------------------------------------------------------------------- #
# analyst_reports
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_analyst_reports_check_and_live_counts():
    rows = bar.build_rows(REPO_ROOT)
    assert bar.check(rows, REPO_ROOT) == []
    schema = _schema(bar.SCHEMA)
    for r in rows:
        assert validate_row(r, schema) == [], r
        assert r["status"] == "done"  # every catalogued report exists
        assert r["row_count"] >= 0
    titles = {r["title"] for r in rows}
    assert "Graph Nodes" in titles and "FOIA Priority Queue" in titles
    # spot-check a live row count
    em = next(r for r in rows if r["path"] == "data/reference/entity_master.csv")
    assert em["row_count"] == 26


@pytest.mark.integration
def test_analyst_reports_regenerates_identically():
    built = {"reports": bar.build_rows(REPO_ROOT)}
    on_disk = json.loads((REPO_ROOT / bar.OUT).read_text(encoding="utf-8"))
    assert on_disk == built


# --------------------------------------------------------------------------- #
# dashboard_app (static HTML explorer)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_dashboard_html_is_deterministic_and_valid():
    html_a = bde.build_html(REPO_ROOT)
    html_b = bde.build_html(REPO_ROOT)
    assert html_a == html_b  # no timestamp / volatile content in the body
    assert bde.check(html_a, REPO_ROOT) == []
    for marker in bde.REQUIRED_MARKERS:
        assert marker in html_a


@pytest.mark.unit
def test_dashboard_embeds_valid_payload():
    data = bde.build_data(REPO_ROOT)
    assert data["reports"] and data["lineage"]
    counts = data["gap_summary"]["status_counts"]
    # the matrix summary embedded in the page reflects the committed gap matrix
    assert counts.get("done", 0) >= 29


@pytest.mark.integration
def test_dashboard_html_regenerates_identically():
    on_disk = (REPO_ROOT / bde.OUT).read_text(encoding="utf-8")
    assert on_disk == bde.build_html(REPO_ROOT)
