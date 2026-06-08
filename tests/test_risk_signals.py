"""Unit tests for the R7 risk signal engine and gates."""

from __future__ import annotations

import csv

import pandas as pd
import pytest

import contract_sweeper.runtime.risk_signals as rs
import contract_sweeper.runtime.risk_signal_gates as rsg


# ---------- Fixtures ----------


def _awards_df(**kwargs) -> pd.DataFrame:
    defaults = {
        "award_id": ["A001", "A002", "A003"],
        "recipient_name": ["ACME CORP", "ACME CORP", "BETA LLC"],
        "recipient_name_normalized": ["ACME CORP", "ACME CORP", "BETA"],
        "obligated_amount": ["1000000", "2000000", "100000"],
        "pop_county": ["SAN JUAN", "SAN JUAN", "PONCE"],
        "source_lineage_path": ["file.csv", "file.csv", ""],
        "source_dataset": ["usaspending", "usaspending", ""],
        "source_record_id": ["R1", "R2", ""],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


def _chains_df(**kwargs) -> pd.DataFrame:
    defaults = {
        "chain_id": ["C001", "C002"],
        "award_id": ["A001", "A002"],
        "project_id": ["P1", "P2"],
        "prime_name": ["ACME CORP", "BETA LLC"],
        "prime_parent_uei": ["UEI001", ""],
        "sub_name": ["SUB CORP", "OTHER SUB"],
        "sub_uei": ["", "SUBUEI2"],
        "sub_parent_uei": ["UEI001", ""],
        "link_confidence": ["0.75", "0.95"],
        "manual_review_required": ["false", "false"],
        "obligation_amount": ["1000000", "500000"],
        "municipality": ["SAN JUAN", "PONCE"],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


def _emma_df(**kwargs) -> pd.DataFrame:
    defaults = {
        "issuer_name": ["ACME CORP", "PUERTO RICO HIGHWAYS"],
        "cusip": ["12345ABC", "67890DEF"],
        "par_amount": ["5000000", "10000000"],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


def _lda_df(**kwargs) -> pd.DataFrame:
    defaults = {
        "client_name": ["ACME CORP"],
        "registrant_name": ["LOBBYIST INC"],
        "filing_uuid": ["UUID-001"],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


def _cabilderos_df(**kwargs) -> pd.DataFrame:
    defaults = {
        "client_name": ["ASOCIACION DE CONTRATISTAS PR"],
        "client_normalized": ["ASOCIACION DE CONTRATISTAS PR"],
        "lobbyist_name": ["JOSE RODRIGUEZ MORALES"],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


def _fec_df(**kwargs) -> pd.DataFrame:
    defaults = {
        "contributor_name": ["JOHN SMITH"],
        "contributor_employer": ["ACME CORP"],
        "contribution_receipt_amount": ["2900"],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)


# ---------- Helper constants tests ----------


@pytest.mark.unit
def test_concentration_threshold_is_positive():
    assert rs.CONCENTRATION_THRESHOLD > 0


@pytest.mark.unit
def test_repeat_award_threshold_is_positive():
    assert rs.REPEAT_AWARD_THRESHOLD >= 2


@pytest.mark.unit
def test_schema_version_is_r7():
    assert rs.SCHEMA_VERSION.startswith("r7")


@pytest.mark.unit
def test_signal_columns_count():
    assert len(rs.SIGNAL_COLUMNS) >= 13


# ---------- _normalize tests ----------


@pytest.mark.unit
def test_normalize_strips_llc():
    assert rs._normalize("ACME LLC") == "ACME"


@pytest.mark.unit
def test_normalize_upper():
    assert rs._normalize("acme corp") == "ACME"


@pytest.mark.unit
def test_normalize_empty():
    assert rs._normalize("") == ""


# ---------- _to_float tests ----------


@pytest.mark.unit
def test_to_float_basic():
    assert rs._to_float("1,000,000") == 1_000_000.0


@pytest.mark.unit
def test_to_float_bad_returns_default():
    assert rs._to_float("N/A", 0.0) == 0.0


# ---------- Concentration signal tests ----------


@pytest.mark.unit
def test_signals_concentration_fires_on_dominant_entity():
    awards = _awards_df()
    sigs = rs._signals_concentration(awards)
    # ACME CORP has 3M of 3.1M = 96.7% — should fire
    assert any(s["signal_family"] == "concentration" and "ACME" in s["entity_name"] for s in sigs)


@pytest.mark.unit
def test_signals_concentration_empty_df():
    sigs = rs._signals_concentration(pd.DataFrame())
    assert sigs == []


@pytest.mark.unit
def test_signals_concentration_high_severity_above_40pct():
    awards = _awards_df(
        award_id=["A1"],
        recipient_name=["MEGA CORP"],
        recipient_name_normalized=["MEGA CORP"],
        obligated_amount=["5000000"],
        pop_county=["SAN JUAN"],
        source_lineage_path=["f"],
        source_dataset=["x"],
        source_record_id=["1"],
    )
    sigs = rs._signals_concentration(awards)
    assert sigs[0]["severity"] == "high"


# ---------- Repeat awards tests ----------


@pytest.mark.unit
def test_signals_repeat_awards_fires_for_acme():
    awards = pd.DataFrame(
        {
            "award_id": ["A001", "A002", "A003"],
            "recipient_name": ["ACME CORP", "ACME CORP", "ACME CORP"],
            "recipient_name_normalized": ["ACME CORP", "ACME CORP", "ACME CORP"],
            "obligated_amount": ["500000", "500000", "500000"],
        }
    )
    sigs = rs._signals_repeat_awards(awards)
    assert any(s["signal_family"] == "repeat_awards" and "ACME" in s["entity_name"] for s in sigs)


@pytest.mark.unit
def test_signals_repeat_awards_respects_threshold():
    awards = pd.DataFrame(
        {
            "award_id": ["A1", "A2"],
            "recipient_name": ["SOLO CORP", "SOLO CORP"],
            "obligated_amount": ["100", "200"],
        }
    )
    sigs = rs._signals_repeat_awards(awards)
    # 2 awards < threshold of 3
    assert not any(s["signal_family"] == "repeat_awards" for s in sigs)


# ---------- Subaward opacity tests ----------


@pytest.mark.unit
def test_signals_subaward_opacity_missing_sub_uei():
    chains = _chains_df()
    sigs = rs._signals_subaward_opacity(chains)
    # C001 has empty sub_uei
    opacity_sigs = [s for s in sigs if s["signal_family"] == "subaward_opacity"]
    assert any("missing_sub_uei" in s["explanation"] for s in opacity_sigs)


@pytest.mark.unit
def test_signals_subaward_opacity_low_confidence():
    chains = _chains_df(sub_uei=["S1", "S2"], link_confidence=["0.50", "0.95"])
    sigs = rs._signals_subaward_opacity(chains)
    opacity_sigs = [s for s in sigs if s["signal_family"] == "subaward_opacity"]
    assert any("low_link_confidence" in s["explanation"] for s in opacity_sigs)


# ---------- Parent-sub mismatch tests ----------


@pytest.mark.unit
def test_signals_parent_sub_mismatch_fires_on_shared_uei():
    chains = _chains_df()
    sigs = rs._signals_parent_sub_mismatch(chains)
    # C001: prime_parent_uei == sub_parent_uei == UEI001
    mismatch = [s for s in sigs if s["signal_family"] == "parent_sub_mismatch"]
    assert len(mismatch) == 1
    assert "UEI001" in mismatch[0]["explanation"]


@pytest.mark.unit
def test_signals_parent_sub_mismatch_no_fire_empty_uei():
    chains = _chains_df(prime_parent_uei=["", ""])
    sigs = rs._signals_parent_sub_mismatch(chains)
    assert not any(s["signal_family"] == "parent_sub_mismatch" for s in sigs)


# ---------- Political overlap tests ----------


@pytest.mark.unit
def test_signals_political_overlap_lda_match():
    awards = _awards_df()
    lda = _lda_df()
    sigs = rs._signals_political_overlap(awards, lda, pd.DataFrame(), pd.DataFrame())
    pol = [s for s in sigs if s["signal_type"] == "lobbying_client_is_awardee"]
    assert len(pol) >= 1


@pytest.mark.unit
def test_signals_political_overlap_fec_employer_match():
    awards = _awards_df()
    fec = _fec_df()
    sigs = rs._signals_political_overlap(awards, pd.DataFrame(), fec, pd.DataFrame())
    fec_sigs = [s for s in sigs if s["signal_type"] == "fec_contributor_employer_is_awardee"]
    assert len(fec_sigs) >= 1


@pytest.mark.unit
def test_signals_political_overlap_empty_sources():
    sigs = rs._signals_political_overlap(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    )
    assert sigs == []


# ---------- Bond-contract overlap tests ----------


@pytest.mark.unit
def test_signals_bond_contract_overlap_fires():
    awards = _awards_df()
    emma = _emma_df()
    sigs = rs._signals_bond_contract_overlap(awards, emma)
    bond = [s for s in sigs if s["signal_family"] == "bond_contract_overlap"]
    assert len(bond) >= 1
    assert "ACME" in bond[0]["entity_name"]


@pytest.mark.unit
def test_signals_bond_contract_overlap_empty_emma():
    sigs = rs._signals_bond_contract_overlap(_awards_df(), pd.DataFrame())
    assert sigs == []


# ---------- Geographic clustering tests ----------


@pytest.mark.unit
def test_signals_geographic_clustering_fires_for_san_juan():
    awards = _awards_df()
    sigs = rs._signals_geographic_clustering(awards)
    geo = [s for s in sigs if s["signal_family"] == "geographic_clustering"]
    assert any(s["subject_id"] == "SAN JUAN" for s in geo)


@pytest.mark.unit
def test_signals_geographic_clustering_empty():
    sigs = rs._signals_geographic_clustering(pd.DataFrame())
    assert sigs == []


# ---------- Stale lineage tests ----------


@pytest.mark.unit
def test_signals_stale_lineage_fires_on_missing_fields():
    awards = _awards_df()
    sigs = rs._signals_stale_lineage(awards)
    # A003 has empty source_lineage_path, source_dataset, source_record_id
    stale = [s for s in sigs if s["signal_family"] == "stale_lineage"]
    assert len(stale) >= 1


@pytest.mark.unit
def test_signals_stale_lineage_no_fire_when_complete():
    awards = pd.DataFrame(
        {
            "award_id": ["A1"],
            "recipient_name": ["ACME CORP"],
            "source_lineage_path": ["file.csv"],
            "source_dataset": ["usaspending"],
            "source_record_id": ["R999"],
            "obligated_amount": ["1000"],
            "pop_county": ["SAN JUAN"],
        }
    )
    sigs = rs._signals_stale_lineage(awards)
    assert not any(s["signal_family"] == "stale_lineage" for s in sigs)


# ---------- Score aggregation tests ----------


@pytest.mark.unit
def test_compute_entity_scores_returns_sorted_desc():
    awards = _awards_df()
    sigs = (
        rs._signals_concentration(awards)
        + rs._signals_repeat_awards(awards)
        + rs._signals_political_overlap(awards, _lda_df(), _fec_df(), pd.DataFrame())
    )
    scores = rs._compute_entity_scores(sigs)
    risk_vals = [s["risk_score"] for s in scores]
    assert risk_vals == sorted(risk_vals, reverse=True)


@pytest.mark.unit
def test_compute_entity_scores_risk_in_0_1():
    awards = _awards_df()
    chains = _chains_df()
    sigs = rs._signals_concentration(awards) + rs._signals_subaward_opacity(chains)
    scores = rs._compute_entity_scores(sigs)
    for s in scores:
        assert 0.0 <= s["risk_score"] <= 1.0


@pytest.mark.unit
def test_compute_project_scores_chains_included():
    chains = _chains_df()
    _awards_df()
    sigs = rs._signals_subaward_opacity(chains)
    scores = rs._compute_project_scores(sigs, chains)
    assert len(scores) == len(chains)


@pytest.mark.unit
def test_compute_municipality_scores_structure():
    awards = _awards_df()
    sigs = rs._signals_geographic_clustering(awards)
    scores = rs._compute_municipality_scores(sigs, awards)
    assert all("municipality" in s and "risk_score" in s for s in scores)


# ---------- compute_signals integration test ----------


@pytest.mark.unit
def test_compute_signals_with_no_data_returns_dict(tmp_path):
    result = rs.compute_signals(tmp_path)
    assert set(result.keys()) == {
        "signals",
        "entity_scores",
        "project_scores",
        "municipality_scores",
        "metadata",
    }
    assert result["metadata"]["schema_version"] == rs.SCHEMA_VERSION


@pytest.mark.unit
def test_compute_signals_with_seed_data(tmp_path):
    # Plant minimal awards CSV
    awards_dir = tmp_path / "data" / "staging" / "processed"
    awards_dir.mkdir(parents=True)
    awards_path = awards_dir / "pr_all_awards_master.csv"
    awards_path.write_text(
        "award_id,recipient_name,recipient_name_normalized,obligated_amount,"
        "pop_county,source_lineage_path,source_dataset,source_record_id\n"
        "A001,ACME CORP,ACME CORP,1000000,SAN JUAN,f.csv,usaspending,R1\n"
        "A002,ACME CORP,ACME CORP,2000000,SAN JUAN,f.csv,usaspending,R2\n"
        "A003,BETA LLC,BETA,100000,PONCE,,,\n",
        encoding="utf-8",
    )

    # Plant minimal chains CSV
    chains_dir = awards_dir / "execution"
    chains_dir.mkdir()
    chains_path = chains_dir / "execution_chain_master.csv"
    chains_path.write_text(
        "chain_id,award_id,project_id,prime_name,prime_parent_uei,sub_name,"
        "sub_uei,sub_parent_uei,link_confidence,manual_review_required,"
        "obligation_amount,municipality\n"
        "C001,A001,P1,ACME CORP,UEI001,SUB CORP,,UEI001,0.75,false,1000000,SAN JUAN\n",
        encoding="utf-8",
    )

    result = rs.compute_signals(tmp_path)
    assert result["metadata"]["input_rows"]["awards"] == 3
    assert result["metadata"]["input_rows"]["chains"] == 1
    assert result["metadata"]["signal_count"] > 0
    assert len(result["entity_scores"]) > 0


# ---------- R7 gate tests ----------


@pytest.mark.unit
def test_gate_signal_schema_valid_no_file(tmp_path):
    r = rsg.gate_signal_schema_valid(tmp_path)
    assert r["passed"] is False


@pytest.mark.unit
def test_gate_signal_schema_valid_passes(tmp_path):
    path = tmp_path / "data" / "staging" / "processed" / "risk"
    path.mkdir(parents=True)
    row = {c: "x" for c in rs.SIGNAL_COLUMNS}
    with (path / "risk_signals_master.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rs.SIGNAL_COLUMNS)
        w.writeheader()
        w.writerow(row)
    r = rsg.gate_signal_schema_valid(tmp_path)
    assert r["passed"] is True


@pytest.mark.unit
def test_gate_signal_lineage_complete_fails_on_empty_evidence(tmp_path):
    path = tmp_path / "data" / "staging" / "processed" / "risk"
    path.mkdir(parents=True)
    row = {c: "x" for c in rs.SIGNAL_COLUMNS}
    row["evidence_source"] = ""
    with (path / "risk_signals_master.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rs.SIGNAL_COLUMNS)
        w.writeheader()
        w.writerow(row)
    r = rsg.gate_signal_lineage_complete(tmp_path)
    assert r["passed"] is False


@pytest.mark.unit
def test_gate_signal_explainability_complete_fails_on_empty_explanation(tmp_path):
    path = tmp_path / "data" / "staging" / "processed" / "risk"
    path.mkdir(parents=True)
    row = {c: "x" for c in rs.SIGNAL_COLUMNS}
    row["explanation"] = ""
    with (path / "risk_signals_master.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rs.SIGNAL_COLUMNS)
        w.writeheader()
        w.writerow(row)
    r = rsg.gate_signal_explainability_complete(tmp_path)
    assert r["passed"] is False


@pytest.mark.unit
def test_gate_no_random_scores_detects_duplicate_ids(tmp_path):
    path = tmp_path / "data" / "staging" / "processed" / "risk"
    path.mkdir(parents=True)
    row = {c: "x" for c in rs.SIGNAL_COLUMNS}
    row["signal_id"] = "DUPLICATE"
    with (path / "risk_signals_master.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rs.SIGNAL_COLUMNS)
        w.writeheader()
        w.writerow(row)
        w.writerow(row)
    r = rsg.gate_no_random_scores(tmp_path)
    assert r["passed"] is False


@pytest.mark.unit
def test_gate_entity_scores_present_fails_missing(tmp_path):
    r = rsg.gate_entity_scores_present(tmp_path)
    assert r["passed"] is False


@pytest.mark.unit
def test_run_all_gates_returns_five_records(tmp_path):
    records = rsg.run_all_gates(tmp_path)
    assert len(records) == 5
    names = {r["gate"] for r in records}
    assert "risk_signal_schema_valid" in names
    assert "entity_scores_present" in names
