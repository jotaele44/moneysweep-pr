from __future__ import annotations

import csv
import json

import pytest

from scripts import entity_resolution as er

pytestmark = pytest.mark.unit


def test_default_entity_resolution_does_not_call_live_api(tmp_path, monkeypatch):
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    master = processed / "pr_contracts_master.csv"
    with master.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["vendor_name", "obligated_amount", "recipient_uei"])
        writer.writeheader()
        writer.writerow(
            {"vendor_name": "Example Vendor", "obligated_amount": "100", "recipient_uei": ""}
        )

    monkeypatch.setattr(
        er,
        "search_recipient",
        lambda *_: (_ for _ in ()).throw(AssertionError("live API called")),
    )
    output = er.run(root=tmp_path, top_n=10)
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert rows[0]["source"] == "offline_unresolved"


def test_default_entity_resolution_reuses_existing_cache(tmp_path):
    processed = tmp_path / "data" / "staging" / "processed"
    enrichment = processed / "enrichment"
    enrichment.mkdir(parents=True)
    with (processed / "pr_contracts_master.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["vendor_name", "obligated_amount", "recipient_uei"])
        writer.writeheader()
        writer.writerow(
            {"vendor_name": "Example Vendor", "obligated_amount": "100", "recipient_uei": ""}
        )
    (enrichment / "entity_cache.json").write_text(
        json.dumps(
            {
                "Example Vendor": {
                    "uei": "EXAMPLEUEI01",
                    "parent_uei": "PARENTUEI001",
                    "parent_name": "Example Parent",
                    "identity_status": "PASS",
                    "binding_basis": "STABLE_ID",
                }
            }
        ),
        encoding="utf-8",
    )
    output = er.run(root=tmp_path, top_n=10)
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert rows[0]["source"] == "cache"
    assert rows[0]["parent_uei"] == "PARENTUEI001"
    assert rows[0]["identity_status"] == "PASS"


def test_legacy_cache_entry_without_identity_status_is_not_stuck_unresolved():
    """A cache entry written before identity_status/binding_basis existed (e.g.
    an old entity_cache.json) must not be silently treated as a settled cache
    hit that permanently reports the safe UNRESOLVED/NONE defaults even though
    it carries real parent_uei/parent_name data -- see resolve_vendor() in
    scripts/entity_resolution.py. It should instead be treated as a cache miss
    for adjudication purposes and fall through to the same path a fresh,
    non-cached lookup takes.
    """
    vendor = {
        "vendor_name": "Legacy Vendor",
        "total_obligation": 100,
        "record_count": 1,
    }
    cache = {
        "Legacy Vendor": {
            "uei": "LEGACYUEI001",
            "parent_uei": "PARENTUEI002",
            "parent_name": "Legacy Parent",
            # No identity_status/binding_basis: pre-dates those fields.
        }
    }

    result = er.resolve_vendor(vendor, sam_index={}, cache=cache, logger=None, use_api=False)

    # It must not be reported as a resolved cache hit that silently keeps the
    # stale UNRESOLVED/NONE defaults alongside real parent data.
    assert result["source"] != "cache"
