"""Tests for scripts/execution_chain_builder.py."""
import csv
from pathlib import Path

import pytest

from scripts.execution_chain_builder import build_execution_chains, _link_confidence


@pytest.fixture
def chain_repo(tmp_path):
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True)

    awards = [
        {"award_id": "AW001", "recipient_name": "Prime Corp", "recipient_uei": "PUEI001",
         "obligated_amount": "5000000", "awarding_agency": "FEMA",
         "cfda_number": "97.036", "pop_county": "San Juan"},
        {"award_id": "AW002", "recipient_name": "Another Prime", "recipient_uei": "PUEI002",
         "obligated_amount": "2000000", "awarding_agency": "HUD",
         "cfda_number": "14.228", "pop_county": "Ponce"},
    ]
    _write_csv(proc / "pr_all_awards_master.csv", awards)

    subs = [
        {"prime_award_id": "AW001", "prime_recipient_name": "Prime Corp",
         "prime_uei": "PUEI001", "sub_recipient_name": "Sub LLC",
         "sub_uei": "SUEI001", "obligated_amount": "250000",
         "pop_county": "San Juan", "subaward_id": "SA001"},
        {"prime_award_id": "AW002", "prime_recipient_name": "Another Prime",
         "prime_uei": "PUEI002", "sub_recipient_name": "Sub Two Inc",
         "sub_uei": "SUEI002", "obligated_amount": "100000",
         "pop_county": "Ponce", "subaward_id": "SA002"},
        # record without matching prime (subaward_record_only)
        {"prime_award_id": "UNKNOWN_AW", "prime_recipient_name": "Ghost Prime",
         "prime_uei": "", "sub_recipient_name": "Orphan Sub",
         "sub_uei": "", "obligated_amount": "50000",
         "pop_county": "", "subaward_id": "SA003"},
    ]
    _write_csv(proc / "pr_subawards_master.csv", subs)

    return tmp_path


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


@pytest.mark.unit
def test_build_chains_returns_summary_keys(chain_repo):
    result = build_execution_chains(chain_repo)
    for key in ("chain_count", "linked_to_prime", "linkage_rate", "full_chain_rate",
                "review_queue_count", "per_asset_count", "per_municipality_count", "outputs"):
        assert key in result


@pytest.mark.unit
def test_build_chains_emits_output_files(chain_repo):
    build_execution_chains(chain_repo)
    out = chain_repo / "data" / "staging" / "processed" / "execution"
    assert (out / "execution_chain_master.csv").exists()
    assert (out / "execution_chain_per_asset.csv").exists()
    assert (out / "execution_chain_per_municipality.csv").exists()
    assert (out / "execution_chain_review_queue.csv").exists()


@pytest.mark.unit
def test_build_chains_count(chain_repo):
    result = build_execution_chains(chain_repo)
    assert result["chain_count"] == 3


@pytest.mark.unit
def test_build_chains_linkage_rate(chain_repo):
    result = build_execution_chains(chain_repo)
    # 2 of 3 subawards have matching prime award_id → linkage_rate = 2/3
    assert abs(result["linkage_rate"] - 2 / 3) < 0.01


@pytest.mark.unit
def test_build_chains_per_municipality(chain_repo):
    result = build_execution_chains(chain_repo)
    out = chain_repo / "data" / "staging" / "processed" / "execution"
    with (out / "execution_chain_per_municipality.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # San Juan and Ponce present; UNKNOWN also present for orphan sub
    munis = {r["municipality"] for r in rows}
    assert "San Juan" in munis or "Ponce" in munis


@pytest.mark.unit
def test_build_chains_link_method(chain_repo):
    build_execution_chains(chain_repo)
    out = chain_repo / "data" / "staging" / "processed" / "execution"
    with (out / "execution_chain_master.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    methods = {r["link_method"] for r in rows}
    assert "prime_award_id_join" in methods
    assert "subaward_record_only" in methods


@pytest.mark.unit
def test_link_confidence_full_match():
    score = _link_confidence("AW001", "Prime Corp", "Sub LLC", "PUEI001", "SUEI001", True)
    assert score == 1.0


@pytest.mark.unit
def test_link_confidence_no_data():
    score = _link_confidence("", "", "", "", "", False)
    assert score == 0.0


@pytest.mark.unit
def test_link_confidence_partial():
    # Only award_id + prime_in_index → 0.35 + 0.15 = 0.50
    score = _link_confidence("AW001", "", "", "", "", True)
    assert abs(score - 0.50) < 0.01
