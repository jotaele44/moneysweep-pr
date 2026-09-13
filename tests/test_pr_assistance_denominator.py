"""Contract tests for the Puerto Rico financial-assistance denominator lane."""

from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.download_pr_assistance_denominator import (
    ASSISTANCE_FILTER_CODES,
    _load_sam_financial_programs,
    _payload,
    aggregate,
)
from scripts.recover_pr_assistance_failed_shards import _wait_for_job

pytestmark = pytest.mark.unit


def test_endpoint_filter_denominator_is_all_legacy_financial_assistance_codes():
    assert ASSISTANCE_FILTER_CODES == [
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
        "10",
        "11",
    ]


def test_recipient_and_place_of_performance_are_independent_nexus_filters():
    recipient = _payload(2026, "recipient")["filters"]
    pop = _payload(2026, "pop")["filters"]
    assert recipient["recipient_locations"] == [{"country": "USA", "state": "PR"}]
    assert "place_of_performance_locations" not in recipient
    assert pop["place_of_performance_locations"] == [{"country": "USA", "state": "PR"}]
    assert "recipient_locations" not in pop
    assert recipient["prime_award_types"] == pop["prime_award_types"] == ASSISTANCE_FILTER_CODES


def _write_sam(path: Path) -> str:
    frame = pd.DataFrame(
        [
            {
                "Program Title": "Program One",
                "Program Number": "01.001",
                "Federal Agency (030)": "Agency A",
                "Types of Assistance (060)": "PROJECT GRANTS",
            },
            {
                "Program Title": "Program Two",
                "Program Number": "01.002",
                "Federal Agency (030)": "Agency B",
                "Types of Assistance (060)": "DIRECT PAYMENTS FOR SPECIFIED USE",
            },
        ]
    )
    frame.to_csv(path, index=False, encoding="cp1252")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_receipt(path: Path, *, fy: int, nexus: str, rows: int, status: str = "complete") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "pr_assistance_shard_receipt_v1",
                "fiscal_year": fy,
                "nexus": nexus,
                "status": status,
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )


def test_aggregate_deduplicates_hard_award_keys_and_classifies_full_program_denominator(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    sam = tmp_path / "sam.csv"
    sam_hash = _write_sam(sam)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "source": {"sha256": sam_hash},
                "denominator": {"financial_program_rows": 2},
            }
        ),
        encoding="utf-8",
    )

    recipient = pd.DataFrame(
        [
            {
                "assistance_listing_number": "01.001",
                "assistance_award_unique_key": "ASST_TEST_1",
                "moneysweep_pr_nexus_evidence": "recipient",
                "moneysweep_source_fiscal_year": "2026",
            }
        ]
    )
    pop = recipient.copy()
    pop["moneysweep_pr_nexus_evidence"] = "pop"
    recipient.to_csv(raw / "pr_assistance_recipient_fy2026.csv", index=False)
    pop.to_csv(raw / "pr_assistance_pop_fy2026.csv", index=False)
    _write_receipt(
        raw / "pr_assistance_recipient_fy2026.receipt.json", fy=2026, nexus="recipient", rows=1
    )
    _write_receipt(raw / "pr_assistance_pop_fy2026.receipt.json", fy=2026, nexus="pop", rows=1)

    out = tmp_path / "out"
    coverage = aggregate(raw, out, snapshot, sam, 2026, 2026)
    assert coverage["financial_program_denominator"] == 2
    assert coverage["programs_classified"] == 2
    assert coverage["program_classification_pct"] == 100.0
    assert coverage["deduplicated_prime_awards"] == 1
    assert coverage["confirmed_program_numbers"] == 1
    assert coverage["pr_nexus_state_counts"] == {
        "confirmed_pr_activity": 1,
        "unresolved": 1,
    }
    assert coverage["global_fain_backfill_allowed"] is False

    awards = pd.read_csv(out / "pr_assistance_prime_awards_native_dedup.csv", dtype=str)
    assert len(awards) == 1
    assert awards.iloc[0]["moneysweep_pr_nexus_evidence_set"] == "pop;recipient"

    ledger = pd.read_csv(out / "pr_financial_program_pr_nexus_adjudication.csv", dtype=str)
    states = dict(zip(ledger["program_number"], ledger["pr_nexus_state"], strict=True))
    assert states == {"01.001": "confirmed_pr_activity", "01.002": "unresolved"}


def test_aggregate_fails_closed_when_any_fiscal_year_nexus_shard_is_missing(tmp_path):
    sam = tmp_path / "sam.csv"
    sam_hash = _write_sam(sam)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({"source": {"sha256": sam_hash}, "denominator": {"financial_program_rows": 2}}),
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_receipt(raw / "only_one.receipt.json", fy=2026, nexus="recipient", rows=0)
    with pytest.raises(RuntimeError, match="incomplete shard denominator"):
        aggregate(raw, tmp_path / "out", snapshot, sam, 2026, 2026)


def test_aggregate_rejects_equal_sized_wrong_shard_set(tmp_path):
    sam = tmp_path / "sam.csv"
    sam_hash = _write_sam(sam)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({"source": {"sha256": sam_hash}, "denominator": {"financial_program_rows": 2}}),
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_receipt(raw / "recipient.receipt.json", fy=2026, nexus="recipient", rows=0)
    _write_receipt(raw / "wrong.receipt.json", fy=2025, nexus="pop", rows=0)
    with pytest.raises(RuntimeError, match=r"missing=.*2026.*pop.*extra=.*2025.*pop"):
        aggregate(raw, tmp_path / "out", snapshot, sam, 2026, 2026)


def test_aggregate_rejects_duplicate_complete_shard_receipts(tmp_path):
    sam = tmp_path / "sam.csv"
    sam_hash = _write_sam(sam)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({"source": {"sha256": sam_hash}, "denominator": {"financial_program_rows": 2}}),
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_receipt(raw / "recipient-a.receipt.json", fy=2026, nexus="recipient", rows=0)
    _write_receipt(raw / "recipient-b.receipt.json", fy=2026, nexus="recipient", rows=0)
    _write_receipt(raw / "pop.receipt.json", fy=2026, nexus="pop", rows=0)
    with pytest.raises(RuntimeError, match=r"duplicates=.*2026.*recipient"):
        aggregate(raw, tmp_path / "out", snapshot, sam, 2026, 2026)


def test_aggregate_counts_rows_from_complete_receipts_only(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    sam = tmp_path / "sam.csv"
    sam_hash = _write_sam(sam)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({"source": {"sha256": sam_hash}, "denominator": {"financial_program_rows": 2}}),
        encoding="utf-8",
    )
    _write_receipt(raw / "recipient.receipt.json", fy=2026, nexus="recipient", rows=3)
    _write_receipt(raw / "pop.receipt.json", fy=2026, nexus="pop", rows=4)
    _write_receipt(
        raw / "failed.receipt.json", fy=2026, nexus="recipient", rows=99, status="failed"
    )
    coverage = aggregate(raw, tmp_path / "out", snapshot, sam, 2026, 2026)
    assert coverage["native_rows_before_dedup"] == 7


def test_frozen_sam_source_must_exist_and_never_falls_back_to_network(tmp_path):
    missing = tmp_path / "missing.csv.gz"
    with pytest.raises(RuntimeError, match="frozen SAM denominator source is missing"):
        _load_sam_financial_programs(missing, "0" * 64)


def test_frozen_sam_source_validates_transport_and_logical_hashes(tmp_path):
    source = tmp_path / "sam.csv"
    logical_hash = _write_sam(source)
    artifact = tmp_path / "sam.csv.gz"
    with gzip.GzipFile(filename="", mode="wb", fileobj=artifact.open("wb"), mtime=0) as output:
        output.write(source.read_bytes())
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    programs = _load_sam_financial_programs(artifact, logical_hash, artifact_hash)
    assert set(programs) == {"01.001", "01.002"}

    with pytest.raises(RuntimeError, match="SAM denominator artifact drift"):
        _load_sam_financial_programs(artifact, logical_hash, "0" * 64)


def test_recovery_404_after_registration_grace_is_terminal(monkeypatch):
    class Session:
        def get(self, *args, **kwargs):
            return requests.Response()

    response = requests.Response()
    response.status_code = 404
    monkeypatch.setattr(Session, "get", lambda self, *args, **kwargs: response)
    times = iter((0.0, 181.0, 181.0))
    monkeypatch.setattr(
        "scripts.recover_pr_assistance_failed_shards.time.monotonic", lambda: next(times)
    )
    with pytest.raises(RuntimeError, match="remained unregistered after grace period"):
        _wait_for_job(Session(), {"file_name": "missing-job"})
