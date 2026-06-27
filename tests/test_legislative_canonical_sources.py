from __future__ import annotations

import json

from scripts.fetch_legislative_canonical_sources import (
    _as_string_list,
    _compact_measure_id,
    _spaced_measure_id,
    build_canonical_record,
    run,
)


def test_measure_id_helpers_normalize_pr_identifiers():
    assert _compact_measure_id("PS 782") == "PS782"
    assert _compact_measure_id("P del C 123") == "PC123"
    assert _spaced_measure_id("PS782") == "PS 782"
    assert _spaced_measure_id("pc-1207") == "PC 1207"


def test_as_string_list_preserves_scalar_values():
    assert _as_string_list("bill") == ["bill"]
    assert _as_string_list(["bill", "resolution"]) == ["bill", "resolution"]
    assert _as_string_list(None) == []


def test_build_canonical_record_blocks_without_official_confirmation(monkeypatch):
    monkeypatch.setattr(
        "scripts.fetch_legislative_canonical_sources._url_exists", lambda url: False
    )
    row = build_canonical_record(
        {
            "measure_id": "PS782",
            "source_url": "https://www.legislapr.com/bills/PS%20782",
            "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
            "sutra_url": "https://sutra.oslpr.org/medidas/ps0782-25.doc",
            "title": "Fiscal measure",
        },
        api_key=None,
    )
    assert row.measure_id == "PS 782"
    assert row.canonical_confirmation_status == "partial_confirmation"
    assert row.promotion_status == "blocked_pending_canonical_confirmation"


def test_build_canonical_record_promotes_cross_confirmed_candidate(monkeypatch):
    monkeypatch.setattr("scripts.fetch_legislative_canonical_sources._url_exists", lambda url: True)
    row = build_canonical_record(
        {
            "measure_id": "PS782",
            "source_url": "https://www.legislapr.com/bills/PS%20782",
            "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
            "sutra_url": "https://sutra.oslpr.org/medidas/ps0782-25.doc",
            "title": "Fiscal measure",
        },
        api_key=None,
    )
    assert row.official_document_confirmed is True
    assert row.canonical_confirmation_status == "cross_confirmed"
    assert row.promotion_status == "promoted_candidate"


def test_run_writes_canonical_output_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.fetch_legislative_canonical_sources._url_exists", lambda url: True)
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "measure_id": "PS782",
                    "source_url": "https://www.legislapr.com/bills/PS%20782",
                    "openstates_url": "https://openstates.org/pr/bills/2025-2028/PS782/",
                    "sutra_url": "https://sutra.oslpr.org/medidas/ps0782-25.doc",
                    "title": "Fiscal measure",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run(
        root=tmp_path,
        input_path="input.json",
        output_path="output.json",
        api_key=None,
        allow_missing_key=True,
    )
    assert result["status"] == "OK"
    assert result["promoted_candidates"] == 1
    rows = json.loads(output_path.read_text(encoding="utf-8"))
    assert rows[0]["promotion_status"] == "promoted_candidate"
