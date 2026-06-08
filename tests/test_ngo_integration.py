"""Tests for the additive NGO / OSFL integration layer."""

import json
from pathlib import Path

import pandas as pd

from scripts import ngo_integration as ngo


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    raw = tmp_path / "data" / "raw" / "ngos"
    processed = tmp_path / "data" / "staging" / "processed"
    out = processed / "ngos"
    schema = out / "schema"
    monkeypatch.setattr(ngo, "ROOT", tmp_path)
    monkeypatch.setattr(ngo, "RAW_NGO_DIR", raw)
    monkeypatch.setattr(ngo, "PROCESSED_DIR", processed)
    monkeypatch.setattr(ngo, "NGO_OUT_DIR", out)
    monkeypatch.setattr(ngo, "SCHEMA_OUT_DIR", schema)
    return processed


def test_create_schema_files_writes_required_contracts(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)

    ngo.create_schema_files()

    master_schema = ngo.SCHEMA_OUT_DIR / "ngos_master.schema.json"
    funding_schema = ngo.SCHEMA_OUT_DIR / "ngo_funding_edges.schema.json"
    coverage_schema = ngo.SCHEMA_OUT_DIR / "ngo_municipal_coverage.schema.json"

    assert master_schema.exists()
    assert funding_schema.exists()
    assert coverage_schema.exists()

    payload = json.loads(master_schema.read_text(encoding="utf-8"))
    assert payload["primary_key"] == "ngo_id"
    assert "legal_name" in payload["required"]
    assert payload["municipality_count_required"] == 78


def test_run_pipeline_builds_islandwide_coverage_and_funding_edges(monkeypatch, tmp_path):
    processed = _patch_paths(monkeypatch, tmp_path)
    irs_dir = ngo.RAW_NGO_DIR / "irs_eo_bmf"
    irs_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "EIN": "660000001",
                "Organization Name": "Fundacion Comunitaria Puerto Rico",
                "State": "PR",
                "City": "San Juan",
                "NTEE Code": "S20",
                "Subsection": "03",
                "Address": "123 Calle Principal, San Juan, PR",
            }
        ]
    ).to_csv(irs_dir / "eo_bmf_pr.csv", index=False)

    pd.DataFrame(
        [
            {
                "Award ID": "FAKE-AWARD-001",
                "Recipient Name": "Fundacion Comunitaria Puerto Rico",
                "Awarding Agency Name": "Federal Emergency Management Agency",
                "Federal Action Obligation": "125000.50",
                "Award Description": "Disaster recovery community services",
                "Recipient City Name": "San Juan",
                "Recipient State Code": "PR",
                "Award Date": "2021-04-01",
            }
        ]
    ).to_csv(processed / "pr_contracts_master.csv", index=False)

    summary = ngo.run_pipeline()

    assert summary["status"] == "pass"
    assert summary["municipalities"] == 78
    assert summary["ngos"] == 1
    assert summary["funding_edges"] == 1

    master = pd.read_csv(ngo.NGO_OUT_DIR / "ngos_master.csv")
    edges = pd.read_csv(ngo.NGO_OUT_DIR / "ngo_funding_edges.csv")
    coverage = pd.read_csv(ngo.NGO_OUT_DIR / "ngo_municipal_coverage.csv")

    assert master.loc[0, "municipality"] == "San Juan"
    assert master.loc[0, "confidence"] >= 60
    assert edges.loc[0, "target_ngo_id"] == master.loc[0, "ngo_id"]
    assert len(coverage) == 78
    san_juan = coverage[coverage["municipality"] == "San Juan"].iloc[0]
    assert san_juan["ngo_count_registered"] == 1
    assert san_juan["ngo_count_federally_funded"] >= 1
    assert san_juan["blind_spot_reason"] == "covered"


def test_canonical_source_bonus_lifts_bmf_only_rows(monkeypatch, tmp_path):
    processed = _patch_paths(monkeypatch, tmp_path)
    irs_dir = ngo.RAW_NGO_DIR / "irs_eo_bmf"
    irs_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    # EIN + active IRS status + municipality + legal name = 60 on identity fields
    # alone; the canonical IRS-BMF provenance bonus (+15) lifts it into the
    # strong_probable band.
    pd.DataFrame(
        [
            {
                "EIN": "660000123",
                "Organization Name": "Centro Comunitario de Ponce",
                "State": "PR",
                "City": "Ponce",
                "Subsection": "03",
                "Address": "10 Calle Sol, Ponce, PR",
            }
        ]
    ).to_csv(irs_dir / "eo_bmf_pr.csv", index=False)

    ngo.run_pipeline()
    master = pd.read_csv(ngo.NGO_OUT_DIR / "ngos_master.csv")
    row = master.iloc[0]
    assert row["confidence"] >= 75
    assert row["review_status"] == "strong_probable"


def test_fiscal_sponsor_edges_from_group_exemption(monkeypatch, tmp_path):
    processed = _patch_paths(monkeypatch, tmp_path)
    irs_dir = ngo.RAW_NGO_DIR / "irs_eo_bmf"
    irs_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "EIN": "660000900",
                "Organization Name": "Umbrella Central Inc",
                "State": "PR",
                "City": "San Juan",
                "Group Exemption Number": "1234",
                "Affiliation": "6",
            },
            {
                "EIN": "660000901",
                "Organization Name": "Subordinate Chapter San Juan",
                "State": "PR",
                "City": "San Juan",
                "Group Exemption Number": "1234",
                "Affiliation": "9",
            },
        ]
    ).to_csv(irs_dir / "eo_bmf_pr.csv", index=False)

    summary = ngo.run_pipeline()
    edges = pd.read_csv(ngo.NGO_OUT_DIR / "ngo_fiscal_sponsor_edges.csv")
    assert summary["fiscal_sponsor_edges"] == 1
    assert len(edges) == 1
    central_id = ngo.stable_id("ngo", "660000900", "San Juan")
    sub_id = ngo.stable_id("ngo", "660000901", "San Juan")
    assert edges.loc[0, "sponsor_ngo_id"] == central_id
    assert edges.loc[0, "sponsored_entity"] == sub_id
    assert edges.loc[0, "relationship_type"] == "group_exemption"


def test_asset_edges_link_funded_ngo_to_asset(monkeypatch, tmp_path):
    processed = _patch_paths(monkeypatch, tmp_path)
    irs_dir = ngo.RAW_NGO_DIR / "irs_eo_bmf"
    irs_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "EIN": "660000001",
                "Organization Name": "Fundacion Comunitaria Puerto Rico",
                "State": "PR",
                "City": "San Juan",
                "Address": "123 Calle Principal, San Juan, PR",
            }
        ]
    ).to_csv(irs_dir / "eo_bmf_pr.csv", index=False)

    # Award row carries both an award_id (funding edge) and an asset_id (asset link).
    pd.DataFrame(
        [
            {
                "Award ID": "FAKE-AWARD-001",
                "Recipient Name": "Fundacion Comunitaria Puerto Rico",
                "Awarding Agency Name": "Federal Emergency Management Agency",
                "Federal Action Obligation": "125000.50",
                "Award Description": "Disaster recovery community services",
                "Recipient City Name": "San Juan",
                "Recipient State Code": "PR",
                "asset_id": "PW-555",
            }
        ]
    ).to_csv(processed / "pr_contracts_master.csv", index=False)

    summary = ngo.run_pipeline()
    assets = pd.read_csv(ngo.NGO_OUT_DIR / "ngo_asset_edges.csv")
    coverage = pd.read_csv(ngo.NGO_OUT_DIR / "ngo_municipal_coverage.csv")
    assert summary["asset_edges"] == 1
    assert assets.loc[0, "asset_id"] == "PW-555"
    assert assets.loc[0, "evidence_class"] == "award_id_match"
    san_juan = coverage[coverage["municipality"] == "San Juan"].iloc[0]
    assert san_juan["ngo_count_asset_linked"] == 1


def test_parquet_and_schema_outputs_written(monkeypatch, tmp_path):
    processed = _patch_paths(monkeypatch, tmp_path)
    irs_dir = ngo.RAW_NGO_DIR / "irs_eo_bmf"
    irs_dir.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "EIN": "660000001",
                "Organization Name": "Fundacion Comunitaria Puerto Rico",
                "State": "PR",
                "City": "San Juan",
            }
        ]
    ).to_csv(irs_dir / "eo_bmf_pr.csv", index=False)

    ngo.run_pipeline()
    out = ngo.NGO_OUT_DIR
    # pq_write emits .parquet when pyarrow is present, else a .csv fallback.
    for stem in [
        "ngos_master",
        "ngo_funding_edges",
        "ngo_municipal_coverage",
        "ngo_asset_edges",
        "ngo_fiscal_sponsor_edges",
    ]:
        assert (out / f"{stem}.parquet").exists() or (out / f"{stem}.csv").exists()
    for schema in ["ngo_asset_edges.schema.json", "ngo_fiscal_sponsor_edges.schema.json"]:
        assert (ngo.SCHEMA_OUT_DIR / schema).exists()


def test_consolidate_ngos_deduplicates_by_ein():
    records = pd.DataFrame(
        [
            {
                "ngo_id": "ngo_a",
                "ein": "66-0000001",
                "legal_name": "Fundacion A",
                "municipality": "Ponce",
                "status_irs": "active",
                "status_pr": "unknown",
                "source_ids": json.dumps(["irs:a.csv"]),
                "coverage_municipalities": json.dumps(["Ponce"]),
            },
            {
                "ngo_id": "ngo_b",
                "ein": "660000001",
                "legal_name": "Fundacion A Inc",
                "municipality": "Ponce",
                "status_irs": "unknown",
                "status_pr": "active",
                "source_ids": json.dumps(["pr:b.csv"]),
                "coverage_municipalities": json.dumps(["Ponce"]),
            },
        ]
    )

    consolidated = ngo.consolidate_ngos(records)

    assert len(consolidated) == 1
    assert consolidated.iloc[0]["ein"] == "660000001"
    assert consolidated.iloc[0]["status_pr"] == "active"
    assert "pr:b.csv" in consolidated.iloc[0]["source_ids"]
