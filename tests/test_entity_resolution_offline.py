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
    with output.open(encoding="utf-8") as source_file:
        rows = list(csv.DictReader(source_file))
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
                }
            }
        ),
        encoding="utf-8",
    )
    output = er.run(root=tmp_path, top_n=10)
    with output.open(encoding="utf-8") as source_file:
        rows = list(csv.DictReader(source_file))
    assert rows[0]["source"] == "cache"
    assert rows[0]["parent_uei"] == "PARENTUEI001"
