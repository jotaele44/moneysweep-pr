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

    # A prime contracts master keyed by generated_internal_id — exercises the
    # USAspending generated-internal-id join path.
    contracts = [
        {"contract_id": "W912DY18F0003",
         "generated_internal_id": "CONT_AWD_W912DY18F0003_9700_-NONE-_-NONE-",
         "vendor_name": "Fluor Enterprises", "agency_name": "DOD",
         "obligated_amount": "9000000", "pop_county": "Bayamon"},
    ]
    _write_csv(proc / "pr_contracts_master.csv", contracts)

    subs = [
        # matches pr_all_awards_master by award_id → prime_award_id_join
        {"prime_award_id": "AW001", "prime_award_generated_internal_id": "",
         "prime_recipient_name": "Prime Corp", "prime_uei": "PUEI001",
         "sub_recipient_name": "Sub LLC", "sub_uei": "SUEI001",
         "obligated_amount": "250000", "pop_county": "San Juan", "subaward_id": "SA001"},
        # matches pr_contracts_master by generated_internal_id → prime_award_id_join
        {"prime_award_id": "W912DY18F0003",
         "prime_award_generated_internal_id": "CONT_AWD_W912DY18F0003_9700_-NONE-_-NONE-",
         "prime_recipient_name": "Fluor Enterprises", "prime_uei": "PUEI003",
         "sub_recipient_name": "Sub Two Inc", "sub_uei": "SUEI002",
         "obligated_amount": "100000", "pop_county": "Bayamon", "subaward_id": "SA002"},
        # prime declared in the subaward record but not in any local master
        # → subaward_declared_prime (still a linked chain)
        {"prime_award_id": "70FBR221F00000178",
         "prime_award_generated_internal_id": "CONT_AWD_70FBR221F00000178_7022_X_7022",
         "prime_recipient_name": "Ghost Prime", "prime_uei": "",
         "sub_recipient_name": "Orphan Sub", "sub_uei": "",
         "obligated_amount": "50000", "pop_county": "Caguas", "subaward_id": "SA003"},
        # no prime identifier and no prime name → subaward_record_only
        {"prime_award_id": "", "prime_award_generated_internal_id": "",
         "prime_recipient_name": "", "prime_uei": "",
         "sub_recipient_name": "Nameless Sub", "sub_uei": "",
         "obligated_amount": "25000", "pop_county": "", "subaward_id": "SA004"},
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
    for key in ("chain_count", "linked_to_prime", "enriched_from_prime_index",
                "declared_prime_only", "linkage_rate", "enrichment_rate",
                "full_chain_rate", "review_queue_count", "per_asset_count",
                "per_municipality_count", "outputs"):
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
    assert result["chain_count"] == 4


@pytest.mark.unit
def test_build_chains_linkage_rate(chain_repo):
    result = build_execution_chains(chain_repo)
    # 2 enriched (AW001, generated_internal_id) + 1 declared (Ghost Prime) = 3 linked
    # 1 record-only (Nameless Sub) → linkage_rate = 3/4
    assert abs(result["linkage_rate"] - 0.75) < 0.01
    # only the 2 primes held locally are enriched → enrichment_rate = 2/4
    assert abs(result["enrichment_rate"] - 0.50) < 0.01


@pytest.mark.unit
def test_build_chains_generated_internal_id_join(chain_repo):
    """A subaward whose prime is keyed only by generated_internal_id still joins."""
    build_execution_chains(chain_repo)
    out = chain_repo / "data" / "staging" / "processed" / "execution"
    with (out / "execution_chain_master.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fluor = [r for r in rows if r["sub_name"] == "Sub Two Inc"][0]
    assert fluor["link_method"] == "prime_award_id_join"


@pytest.mark.unit
def test_build_chains_per_municipality(chain_repo):
    result = build_execution_chains(chain_repo)
    out = chain_repo / "data" / "staging" / "processed" / "execution"
    with (out / "execution_chain_per_municipality.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
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
    assert "subaward_declared_prime" in methods
    assert "subaward_record_only" in methods


@pytest.mark.unit
def test_link_confidence_full_match():
    # strong authoritative key + every signal present → 1.0
    score = _link_confidence("AW001", "Prime Corp", "Sub LLC", "PUEI001", "SUEI001",
                             True, True)
    assert score == 1.0


@pytest.mark.unit
def test_link_confidence_no_data():
    score = _link_confidence("", "", "", "", "", False, False)
    assert score == 0.0


@pytest.mark.unit
def test_link_confidence_partial():
    # award id (no strong key) + prime_in_index → 0.25 + 0.15 = 0.40
    score = _link_confidence("AW001", "", "", "", "", True, False)
    assert abs(score - 0.40) < 0.01


@pytest.mark.unit
def test_link_confidence_strong_key_outweighs_plain_id():
    plain = _link_confidence("AW001", "Prime", "Sub", "", "", False, False)
    strong = _link_confidence("AW001", "Prime", "Sub", "", "", False, True)
    assert strong > plain
