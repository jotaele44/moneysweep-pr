"""Tests for moneysweep.runtime.maturity_gate."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from moneysweep.runtime.maturity_gate import (
    DEFAULT_STATUS_CSV,
    claim_tier,
    load_dataset_to_source_map,
    load_source_maturity,
    unmaterialized_sources,
)

FIXTURE = Path(__file__).parent / "fixtures" / "source_registry_status_sample.csv"


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Repo layout with the sample status CSV at the expected path."""
    target = tmp_path / DEFAULT_STATUS_CSV
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, target)
    return tmp_path


@pytest.mark.unit
def test_load_source_maturity_returns_status_map(fixture_repo: Path) -> None:
    maturity = load_source_maturity(fixture_repo)
    assert maturity["emma_bonds"] == "not_materialized"
    assert maturity["fec"] == "fully_materialized"
    assert maturity["lda"] == "partially_materialized"


@pytest.mark.unit
def test_load_source_maturity_missing_csv_returns_empty(tmp_path: Path) -> None:
    assert load_source_maturity(tmp_path) == {}


@pytest.mark.unit
def test_dataset_map_indexes_by_leaf_filename(fixture_repo: Path) -> None:
    dmap = load_dataset_to_source_map(fixture_repo)
    assert dmap["pr_emma_bonds.csv"] == "emma_bonds"
    assert dmap["bond_asset_map.csv"] == "emma_bonds"
    assert dmap["pr_contracts_master.csv"] == "usaspending_prime"


@pytest.mark.unit
def test_claim_tier_observed_for_fully_materialized(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    assert claim_tier(["pr_fec_contributions.csv"], m, dm) == "observed"


@pytest.mark.unit
def test_claim_tier_linked_for_partial(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    assert claim_tier(["pr_lda_filings.csv"], m, dm) == "linked"


@pytest.mark.unit
def test_claim_tier_blocked_for_not_materialized(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    assert claim_tier(["pr_emma_bonds.csv"], m, dm) == "blocked"


@pytest.mark.unit
def test_claim_tier_blocked_for_below_threshold(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    assert claim_tier(["pr_fpds_report_builder.csv"], m, dm) == "blocked"


@pytest.mark.unit
def test_claim_tier_observed_for_no_outputs_declared(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    # Source itself by id (no expected_outputs leaf to index against).
    assert claim_tier(["opencorporates"], m, dm) == "observed"


@pytest.mark.unit
def test_claim_tier_worst_wins_across_multiple(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    tier = claim_tier(
        ["pr_fec_contributions.csv", "pr_lda_filings.csv", "pr_emma_bonds.csv"],
        m,
        dm,
    )
    assert tier == "blocked"


@pytest.mark.unit
def test_claim_tier_unknown_dataset_blocks(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    assert claim_tier(["pr_unknown_source.csv"], m, dm) == "blocked"


@pytest.mark.unit
def test_claim_tier_empty_input_blocks(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    assert claim_tier([], m, dm) == "blocked"


@pytest.mark.unit
def test_unmaterialized_sources_lists_blocked_only(fixture_repo: Path) -> None:
    m = load_source_maturity(fixture_repo)
    dm = load_dataset_to_source_map(fixture_repo)
    blocked = unmaterialized_sources(
        ["pr_fec_contributions.csv", "pr_emma_bonds.csv", "pr_msrb_rtrs_trades.csv"],
        m,
        dm,
    )
    assert sorted(blocked) == ["pr_emma_bonds.csv", "pr_msrb_rtrs_trades.csv"]


@pytest.mark.integration
def test_influence_graph_builder_emits_claim_tier(fixture_repo: Path) -> None:
    """Edges and node metrics must carry claim_tier when maturity CSV is present."""
    from scripts.influence_graph_builder import build_graph

    proc = fixture_repo / "data" / "staging" / "processed"
    proc.mkdir(parents=True, exist_ok=True)

    # Awards from a fully materialized source.
    awards = proc / "pr_all_awards_master.csv"
    with awards.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["award_id", "awarding_agency", "recipient_name", "obligated_amount"]
        )
        w.writeheader()
        w.writerow(
            {
                "award_id": "A1",
                "awarding_agency": "Federal Agency",
                "recipient_name": "Acme Corp",
                "obligated_amount": "1000",
            }
        )

    # EMMA bond row referencing a not-materialized source.
    bonds = proc / "pr_emma_bonds.csv"
    with bonds.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["issuer_name", "underwriter_name", "par_amount", "cusip"])
        w.writeheader()
        w.writerow(
            {
                "issuer_name": "PR Highway Authority",
                "underwriter_name": "Big Bank",
                "par_amount": "500000",
                "cusip": "1234ABC",
            }
        )

    build_graph(fixture_repo)

    edges_path = proc / "graphs" / "entity_edges.csv"
    edges = list(csv.DictReader(edges_path.open(encoding="utf-8")))
    by_dataset = {e["source_dataset"]: e["claim_tier"] for e in edges}
    assert by_dataset.get("pr_all_awards_master.csv") == "observed"
    assert by_dataset.get("pr_emma_bonds.csv") == "blocked"

    top25_path = proc / "graphs" / "top_25_control_entities.csv"
    top25 = list(csv.DictReader(top25_path.open(encoding="utf-8")))
    assert top25, "top_25 should be non-empty"
    # Every node must carry a tier.
    assert all(r.get("claim_tier") in {"observed", "linked", "blocked"} for r in top25)
