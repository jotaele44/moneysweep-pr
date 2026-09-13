from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from scripts import materialize_leaderboard_git_snapshot as replay


def _csvs() -> dict[str, bytes]:
    return {
        "contracts.csv": (
            "contract_id,contract_number,awarding_entity_id,contractor_entity_id,project_id,service_type,award_amount,currency,start_date,end_date,status,confidence,evidence_id,review_status,notes\n"
        ).encode(),
        "entities.csv": (
            "entity_id,name,normalized_name,entity_type,parent_entity_id,jurisdiction,registry_ids,confidence,evidence_id,review_status,notes\n"
            "e1,Issuer One,ISSUER ONE,agency,,PR,,0.9,ev1,accepted,\n"
            "e2,Issuer Two,ISSUER TWO,agency,,PR,,0.9,ev2,accepted,\n"
        ).encode(),
        "edges.csv": "edge_id,source_node_id,target_node_id,edge_type,confidence,evidence_id,review_status,notes\n".encode(),
        "municipalities.csv": "municipality_id,name,normalized_name,confidence,evidence_id,review_status,notes\n".encode(),
        "debt_instruments.csv": (
            "debt_id,issuer_entity_id,debt_class,series,issue_year,par_amount,currency,maturity_date,status,confidence,evidence_id,review_status,notes\n"
            "d1,e1,GO,2025A,2025,100,USD,2040-01-01,,0.9,ev3,accepted,\n"
            "d2,e1,GO,2026A,2026,50,USD,2041-01-01,,0.9,ev4,accepted,\n"
            "d3,e2,other,2026A,2026,80,USD,2042-01-01,,0.9,ev5,accepted,\n"
        ).encode(),
    }


@pytest.mark.unit
def test_source_manifest_binds_exact_git_bytes():
    raw = b"a,b\n1,2\n"
    item = replay._source_manifest(
        "data/canonical_v1/example.csv",
        raw,
        "a" * 40,
        "2026-06-01T00:00:00+00:00",
    )
    assert item["bytes"] == len(raw)
    assert item["sha256"] == hashlib.sha256(raw).hexdigest()
    assert item["sourceCommit"] == "a" * 40
    assert item["manifestationType"] == "GIT_COMMIT_BLOB"


@pytest.mark.unit
def test_load_historical_data_preserves_git_manifestation(monkeypatch):
    source = _csvs()
    monkeypatch.setattr(replay, "_commit_timestamp", lambda _commit: "2026-06-01T00:00:00+00:00")
    monkeypatch.setattr(
        replay,
        "_git_bytes",
        lambda _commit, path: source[path.rsplit("/", 1)[-1]],
    )
    data, manifests = replay._load_historical_data("a" * 40)
    assert set(data) == {"contracts", "entities", "edges", "municipalities", "debt_instruments"}
    assert len(data["debt_instruments"]) == 3
    assert manifests["debt_instruments.csv"]["sourceCommit"] == "a" * 40


@pytest.mark.unit
def test_git_replay_uses_stable_entity_ids_and_single_measure(monkeypatch):
    source = _csvs()
    monkeypatch.setattr(replay, "_commit_timestamp", lambda _commit: "2026-06-01T00:00:00+00:00")
    monkeypatch.setattr(
        replay,
        "_git_bytes",
        lambda _commit, path: source[path.rsplit("/", 1)[-1]],
    )
    ranking, manifests = replay._replay_ranking(
        source_commit="a" * 40,
        category="debt_issuance",
        start_year=None,
        end_year=None,
        municipality=None,
        entity_type=None,
        currency="USD",
    )
    assert ranking["metricType"] == "DEBT_ISSUED_PAR"
    assert ranking["accounting"]["arithmeticClosed"] is True
    assert [(row["entityId"], row["metricValue"], row["rank"]) for row in ranking["rows"]] == [
        ("e1", 150.0, 1),
        ("e2", 80.0, 2),
    ]
    assert ranking["sourceManifestations"][0]["sourceCommit"] == "a" * 40
    assert manifests["debt_instruments.csv"]["manifestationType"] == "GIT_COMMIT_BLOB"


@pytest.mark.unit
def test_git_replay_rejects_staging_backed_category():
    with pytest.raises(SystemExit, match="bounded"):
        replay._replay_ranking(
            source_commit="a" * 40,
            category="federal_grant",
            start_year=None,
            end_year=None,
            municipality=None,
            entity_type=None,
            currency="USD",
        )
