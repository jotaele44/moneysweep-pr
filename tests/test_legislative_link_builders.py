from __future__ import annotations

import json

from scripts.build_osl_sutra_crosswalk import build_crosswalk, run as run_crosswalk
from scripts.ingest_legislapr_sessions import extract_sessions
from scripts.merge_legislapr_registry import _merge_sources


def test_extract_sessions_from_openstates_url_and_manual_session():
    rows = [
        {
            "measure_id": "PS782",
            "source_url": "https://www.legislapr.com/bills/PS%20782",
            "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
        }
    ]
    sessions = extract_sessions(rows, manual_sessions=["2021-2024"])
    ids = {row.session_id for row in sessions}
    assert "2025-2028" in ids
    assert "2021-2024" in ids


def test_build_crosswalk_prefers_canonical_confirmation():
    discovery = [
        {
            "measure_id": "PS782",
            "source_url": "https://www.legislapr.com/bills/PS%20782",
            "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
            "sutra_url": "https://sutra.oslpr.org/medidas/ps0782-25.doc",
            "promotion_status": "cross_confirmed_candidate",
        }
    ]
    canonical = [
        {
            "measure_id": "PS 782",
            "legislapr_url": "https://www.legislapr.com/bills/PS%20782",
            "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
            "sutra_url": "https://sutra.oslpr.org/medidas/ps0782-25.doc",
            "canonical_confirmation_status": "cross_confirmed",
            "promotion_status": "promoted_candidate",
        }
    ]
    rows = build_crosswalk(discovery, canonical)
    assert len(rows) == 1
    assert rows[0].measure_id == "PS 782"
    assert rows[0].official_host == "sutra.oslpr.org"
    assert rows[0].canonical_confirmation_status == "cross_confirmed"
    assert rows[0].promotion_status == "promoted_candidate"
    assert rows[0].link_confidence >= 0.8


def test_crosswalk_run_writes_output(tmp_path):
    discovery = tmp_path / "discovery.json"
    canonical = tmp_path / "canonical.json"
    output = tmp_path / "crosswalk.json"
    discovery.write_text(
        json.dumps(
            [
                {
                    "measure_id": "PS782",
                    "source_url": "https://www.legislapr.com/bills/PS%20782",
                    "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
                    "sutra_url": "https://sutra.oslpr.org/medidas/ps0782-25.doc",
                }
            ]
        ),
        encoding="utf-8",
    )
    canonical.write_text("[]", encoding="utf-8")
    result = run_crosswalk(root=tmp_path, discovery_path="discovery.json", canonical_path="canonical.json", output_path="crosswalk.json")
    assert result["status"] == "OK"
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert rows[0]["measure_compact_id"] == "PS782"


def test_registry_merge_dedupes_existing_source():
    registry = {"sources": [{"source_id": "legislapr_discovery", "family": "old"}]}
    incoming = [{"source_id": "legislapr_discovery", "family": "territorial_legislation"}]
    merged, changed = _merge_sources(registry, incoming)
    assert changed is True
    assert merged["sources"] == incoming
