from __future__ import annotations

import csv
import json

from scripts.build_legislative_document_crosswalk import build_crosswalk, compact_measure_id, is_official_document_url
from scripts.build_legislative_links import build_links
from scripts.ingest_legislapr_sessions import extract_sessions
from scripts.merge_legislapr_registry import _merge_sources


def test_merge_sources_adds_legislapr_without_duplicates():
    registry = {"sources": [{"source_id": "existing", "required": False}]}
    merged, changed = _merge_sources(registry, [{"source_id": "legislapr_discovery", "required": False}])
    assert changed is True
    assert [src["source_id"] for src in merged["sources"]] == ["existing", "legislapr_discovery"]
    merged_again, changed_again = _merge_sources(merged, [{"source_id": "legislapr_discovery", "required": False}])
    assert changed_again is False
    assert len(merged_again["sources"]) == 2


def test_extract_sessions_from_openstates_url_and_manual_session():
    rows = [
        {
            "measure_id": "PS782",
            "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
            "source_url": "https://www.legislapr.com/bills/PS%20782",
        }
    ]
    sessions = extract_sessions(rows, manual_sessions=["2021-2024"])
    ids = {row.session_id for row in sessions}
    assert "2025-2028" in ids
    assert "2021-2024" in ids


def test_document_crosswalk_identifies_official_document_url():
    assert compact_measure_id("P del C 123") == "PC123"
    assert is_official_document_url("https://sutra.oslpr.org/medidas/ps0782-25.doc") is True
    assert is_official_document_url("https://example.com/file.pdf") is False
    rows = build_crosswalk(
        [
            {
                "measure_id": "PS 782",
                "source_url": "https://www.legislapr.com/bills/PS%20782",
                "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
                "document_urls": ["https://sutra.oslpr.org/medidas/ps0782-25.doc"],
            }
        ]
    )
    assert rows[0]["measure_id"] == "PS782"
    assert rows[0]["crosswalk_status"] == "ready"


def test_build_legislative_links_creates_manual_review_candidate():
    measures = [
        {
            "measure_id": "PS782",
            "title": "Asignacion de fondos para San Juan y Departamento de Salud",
            "summary": "Autoriza contratos y presupuesto.",
            "source_url": "https://www.legislapr.com/bills/PS%20782",
        }
    ]
    contracts = [
        {
            "award_id": "A1",
            "awarding_agency": "Departamento de Salud",
            "municipality": "San Juan",
        }
    ]
    links = build_links(measures, contracts)
    assert len(links) == 1
    assert links[0]["measure_id"] == "PS782"
    assert links[0]["review_status"] == "manual_review_required"
    assert "agency_name" in links[0]["evidence_signals"]
