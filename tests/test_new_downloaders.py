"""
Tests for the 15 new downloader scripts added in Round 3 pipeline expansion.

Group A: ED, HHS, DOJ, OIA (USASpending copy-paste pattern)
Group B: HAF, ExIm, Earmarks, NFIP, LIHTC, NMTC
Group C: Act60, Rum Cover-Over, FHLB, PREPA contracts
Group D: PROMESA creditors
"""

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Group A — USASpending copy-paste pattern
# ---------------------------------------------------------------------------

# --- ED ---
from scripts.download_ed import (
    AGENCY_NAME as ED_AGENCY,
    GRANT_TYPE_CODES as ED_GRANT_CODES,
    MASTER_COLUMNS as ED_MASTER_COLS,
    _derive_fiscal_year as ed_derive_fy,
    _build_payload as ed_build_payload,
    _results_to_df as ed_results_to_df,
)


def test_ed_agency_name():
    assert "Education" in ED_AGENCY


def test_ed_grant_type_codes_include_standard():
    assert "02" in ED_GRANT_CODES
    assert "03" in ED_GRANT_CODES


def test_ed_master_columns_has_required_fields():
    for col in ("recipient_name", "obligated_amount", "source_dataset"):
        assert col in ED_MASTER_COLS


def test_ed_derive_fiscal_year_q4():
    assert ed_derive_fy("2022-09-30") == "2022"


def test_ed_derive_fiscal_year_q1():
    # October → new fiscal year
    assert ed_derive_fy("2022-10-15") == "2023"


def test_ed_derive_fiscal_year_invalid():
    assert ed_derive_fy("not-a-date") == ""


def test_ed_build_payload_contains_agency():
    payload = ed_build_payload("grants_only", {"label": "2017f2021", "start_date": "2017-01-01", "end_date": "2021-12-31"})
    agencies = [a["name"] for a in payload.get("filters", {}).get("agencies", [])]
    assert any("Education" in n for n in agencies)


def test_ed_results_to_df_empty():
    df = ed_results_to_df([], "ed_raw_dummy.csv")
    assert df.empty


def test_ed_results_to_df_maps_recipient_name():
    rows = [{"recipient_name": "University of Puerto Rico", "total_obligated_amount": "500000"}]
    df = ed_results_to_df(rows, "ed_raw_dummy.csv")
    assert len(df) == 1
    assert df.iloc[0]["recipient_name"] == "University of Puerto Rico"
    assert df.iloc[0]["source_dataset"] == "ed"


# --- HHS ---
from scripts.download_hhs import (
    AGENCY_NAME as HHS_AGENCY,
    SUBTIER_AGENCIES as HHS_SUBTIERS,
    GRANT_TYPE_CODES as HHS_GRANT_CODES,
    _build_payload as hhs_build_payload,
)


def test_hhs_agency_name():
    assert "Health" in HHS_AGENCY


def test_hhs_subtier_includes_hrsa():
    assert any("Health Resources" in s for s in HHS_SUBTIERS)


def test_hhs_subtier_includes_acf():
    assert any("Children" in s for s in HHS_SUBTIERS)


def test_hhs_build_payload_toptier_only():
    payload = hhs_build_payload("grants_only", {"label": "2020f2024", "start_date": "2020-01-01", "end_date": "2024-12-31"})
    agencies = payload.get("filters", {}).get("agencies", [])
    toptier = [a for a in agencies if a["tier"] == "toptier"]
    assert len(toptier) >= 1


def test_hhs_build_payload_subtier_added():
    payload = hhs_build_payload("grants_only", {"label": "2020f2024", "start_date": "2020-01-01", "end_date": "2024-12-31"},
                                subtier="Health Resources and Services Administration")
    agencies = payload.get("filters", {}).get("agencies", [])
    subtier = [a for a in agencies if a["tier"] == "subtier"]
    assert len(subtier) == 1
    assert subtier[0]["name"] == "Health Resources and Services Administration"


def test_hhs_grant_type_codes_standard():
    assert set(["02", "03", "04", "05"]).issubset(set(HHS_GRANT_CODES))


# --- DOJ ---
from scripts.download_doj_grants import (
    AGENCY_NAME as DOJ_AGENCY,
    GRANT_TYPE_CODES as DOJ_GRANT_CODES,
    MASTER_COLUMNS as DOJ_MASTER_COLS,
    _build_payload as doj_build_payload,
)


def test_doj_agency_name():
    assert "Justice" in DOJ_AGENCY


def test_doj_master_columns_source_dataset():
    assert "source_dataset" in DOJ_MASTER_COLS


def test_doj_build_payload_pr_filter():
    payload = doj_build_payload("grants_only", {"label": "2020f2024", "start_date": "2020-01-01", "end_date": "2024-12-31"})
    recipient_locations = payload.get("filters", {}).get("recipient_locations", [])
    assert any(loc.get("country") == "USA" and loc.get("state") == "PR"
               for loc in recipient_locations), "PR filter missing"


# --- OIA ---
from scripts.download_oia import (
    AGENCY_NAME as OIA_AGENCY,
    SUBTIER_AGENCY as OIA_SUBTIER,
    MASTER_COLUMNS as OIA_MASTER_COLS,
    _build_payload as oia_build_payload,
)


def test_oia_agency_name_interior():
    assert "Interior" in OIA_AGENCY


def test_oia_subtier_is_oia():
    assert "Insular" in OIA_SUBTIER


def test_oia_build_payload_includes_subtier():
    payload = oia_build_payload("grants_only", {"label": "2020f2024", "start_date": "2020-01-01", "end_date": "2024-12-31"})
    agencies = payload.get("filters", {}).get("agencies", [])
    subtier_names = [a["name"] for a in agencies if a["tier"] == "subtier"]
    assert any("Insular" in n for n in subtier_names)


# ---------------------------------------------------------------------------
# Group B — Structured external sources
# ---------------------------------------------------------------------------

# --- HAF ---
from scripts.download_haf import (
    PROGRAM_NUMBERS as HAF_PROGRAMS,
    MASTER_COLUMNS as HAF_MASTER_COLS,
    _build_payload as haf_build_payload,
)


def test_haf_program_numbers_contains_cfda():
    assert "21.026" in HAF_PROGRAMS


def test_haf_build_payload_has_program_filter():
    payload = haf_build_payload("grants_only", {"label": "2021f2026", "start_date": "2021-01-01", "end_date": "2026-12-31"})
    assert "21.026" in str(payload.get("filters", payload))


def test_haf_master_columns_complete():
    for col in ("recipient_name", "obligated_amount", "source_dataset"):
        assert col in HAF_MASTER_COLS


# --- ExIm ---
from scripts.download_exim import (
    AGENCY_NAME as EXIM_AGENCY,
    GRANT_TYPE_CODES as EXIM_GRANT_CODES,
    MASTER_COLUMNS as EXIM_MASTER_COLS,
)


def test_exim_agency_name():
    assert "Export" in EXIM_AGENCY


def test_exim_grant_type_codes_loans():
    assert "07" in EXIM_GRANT_CODES
    assert "08" in EXIM_GRANT_CODES


def test_exim_master_columns_has_source():
    assert "source_dataset" in EXIM_MASTER_COLS
    assert "obligated_amount" in EXIM_MASTER_COLS


# --- Earmarks ---
from scripts.download_earmarks import (
    EARMARK_KEYWORDS,
    EARMARK_COLUMNS,
    _results_to_df as earmarks_results_to_df,
)


def test_earmark_keywords_non_empty():
    assert len(EARMARK_KEYWORDS) >= 3


def test_earmark_keywords_include_cpf():
    joined = " ".join(EARMARK_KEYWORDS).lower()
    assert "community project" in joined or "congressionally directed" in joined


def test_earmark_columns_has_keyword_field():
    assert "earmark_keyword_matched" in EARMARK_COLUMNS


def test_earmarks_results_to_df_empty():
    df = earmarks_results_to_df([], "earmarks_raw_dummy.csv")
    assert df.empty


def test_earmarks_results_to_df_keyword_detection():
    rows = [{
        "recipient_name": "City of San Juan",
        "award_description": "Community Project Funding for flood control infrastructure",
        "total_obligated_amount": "2000000",
        "award_id": "W001",
    }]
    df = earmarks_results_to_df(rows, "earmarks_raw_dummy.csv")
    assert len(df) == 1
    assert df.iloc[0]["earmark_keyword_matched"] != ""


# --- NFIP ---
from scripts.download_nfip import (
    NFIP_COLUMNS,
    OUTPUT_COLUMNS as NFIP_OUTPUT_COLS,
    _records_to_df as nfip_records_to_df,
)


def test_nfip_columns_has_loss_fields():
    for col in ("date_of_loss", "year_of_loss", "paid_building", "paid_contents"):
        assert col in NFIP_OUTPUT_COLS


def test_nfip_records_to_df_empty():
    df = nfip_records_to_df([])
    assert df.empty


def test_nfip_records_to_df_basic():
    records = [{
        "reportedCity": "San Juan",
        "reportedZipCode": "00907",
        "dateOfLoss": "2017-09-20",
        "amountPaidOnBuildingClaim": "45000",
        "amountPaidOnContentsClaim": "5000",
        "yearOfLoss": "2017",
        "floodZone": "AE",
    }]
    df = nfip_records_to_df(records)
    assert len(df) == 1
    assert float(df.iloc[0]["paid_building"]) == pytest.approx(45000.0)


# --- LIHTC ---
from scripts.download_lihtc import (
    LIHTC_COLUMNS,
    _normalize_name as lihtc_normalize,
    _filter_pr,
    _build_output as lihtc_build_output,
)


def test_lihtc_columns_has_developer():
    assert "dev_nm" in LIHTC_COLUMNS
    assert "dev_nm_normalized" in LIHTC_COLUMNS


def test_lihtc_normalize_strips_llc():
    result = lihtc_normalize("Example Housing LLC")
    assert "LLC" not in result
    assert "EXAMPLE HOUSING" in result


def test_lihtc_filter_pr_keeps_pr_rows():
    df = pd.DataFrame({
        "st": ["PR", "FL", "PR", "TX"],
        "proj_nm": ["Project A", "Project B", "Project C", "Project D"],
    })
    filtered = _filter_pr(df, _make_logger())
    assert len(filtered) == 2


def test_lihtc_filter_pr_empty():
    df = pd.DataFrame({"st": ["FL", "TX"], "proj_nm": ["A", "B"]})
    filtered = _filter_pr(df, _make_logger())
    assert filtered.empty


def test_lihtc_build_output_normalizes_names():
    df = pd.DataFrame({
        "proj_nm": ["Residencial Las Palmas"],
        "proj_own_nm": ["Example Inc"],
        "dev_nm": ["Builder LLC"],
        "gen_contractor_nm": ["General Corp"],
        "st": ["PR"],
        "allocamt": ["500000"],
        "yr_pis": ["2019"],
    })
    out = lihtc_build_output(df, _make_logger())
    assert "proj_own_nm_normalized" in out.columns
    assert "INC" not in out.iloc[0]["proj_own_nm_normalized"]


# --- NMTC ---
from scripts.download_nmtc import (
    NMTC_COLUMNS,
    _normalize_name as nmtc_normalize,
    _filter_pr as nmtc_filter_pr,
    _build_output as nmtc_build_output,
)


def test_nmtc_columns_has_allocation():
    assert "allocation_amount" in NMTC_COLUMNS
    assert "allocatee_name" in NMTC_COLUMNS


def test_nmtc_normalize_removes_corp():
    result = nmtc_normalize("Puerto Rico Development Corp")
    assert "CORP" not in result
    assert "PUERTO RICO DEVELOPMENT" in result


def test_nmtc_filter_pr_state_column():
    df = pd.DataFrame({
        "state": ["PR", "NY", "PR"],
        "allocatee_name": ["A", "B", "C"],
    })
    filtered = nmtc_filter_pr(df, _make_logger())
    assert len(filtered) == 2


def test_nmtc_filter_pr_service_area_column():
    df = pd.DataFrame({
        "service_area_states": ["PR, VI", "CA, NY", "PR"],
        "allocatee_name": ["A", "B", "C"],
    })
    filtered = nmtc_filter_pr(df, _make_logger())
    assert len(filtered) >= 2


def test_nmtc_build_output_returns_all_columns():
    df = pd.DataFrame({
        "allocatee_name": ["Example CDE LLC"],
        "allocation_year": ["2021"],
        "allocation_amount": ["10000000"],
        "state": ["PR"],
    })
    out = nmtc_build_output(df, _make_logger())
    for col in NMTC_COLUMNS:
        assert col in out.columns, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Group C — PR-specific sources
# ---------------------------------------------------------------------------

# --- Act 60 ---
from scripts.download_act60 import (
    ACT60_COLUMNS,
    _normalize_name as act60_normalize,
    _records_to_df as act60_records_to_df,
)


def test_act60_columns_complete():
    for col in ("decree_id", "entity_name", "entity_normalized", "decree_type"):
        assert col in ACT60_COLUMNS


def test_act60_normalize_basic():
    result = act60_normalize("Acme Services LLC")
    assert "LLC" not in result
    assert "ACME SERVICES" in result


def test_act60_records_to_df_empty():
    df = act60_records_to_df([], "https://ddec.pr.gov")
    assert list(df.columns) == ACT60_COLUMNS


def test_act60_records_to_df_maps_nombre():
    records = [{"nombre": "Puerto Rico Solar LLC", "tipo_decreto": "Act 60"}]
    df = act60_records_to_df(records, "https://ddec.pr.gov")
    assert len(df) == 1
    assert "PUERTO RICO SOLAR" in df.iloc[0]["entity_normalized"]


def test_act60_records_to_df_defaults_decree_type():
    records = [{"entity_name": "Tech Corp PR"}]
    df = act60_records_to_df(records, "https://ddec.pr.gov")
    assert df.iloc[0]["decree_type"] == "Act 60"


def test_act60_source_url_preserved():
    records = [{"entity_name": "Example LLC"}]
    df = act60_records_to_df(records, "https://data.pr.gov/resource/fmnn-uqb7.json")
    assert "data.pr.gov" in df.iloc[0]["source_url"]


# --- Rum Cover-Over ---
from scripts.download_rum_coverover import (
    RUM_COLUMNS,
    KNOWN_COVEROVER,
)


def test_rum_columns_complete():
    for col in ("fiscal_year", "coverover_amount_pr", "allocation_prepa", "allocation_hta"):
        assert col in RUM_COLUMNS


def test_rum_known_coverover_non_empty():
    assert len(KNOWN_COVEROVER) >= 5


def test_rum_known_coverover_years_sequential():
    years = [int(r["fiscal_year"]) for r in KNOWN_COVEROVER]
    assert years == sorted(years)


def test_rum_known_coverover_allocations_sum_to_coverover():
    for rec in KNOWN_COVEROVER:
        total_alloc = rec["allocation_prepa"] + rec["allocation_hta"] + rec["allocation_general_fund"]
        assert abs(total_alloc - rec["coverover_amount_pr"]) < 1, (
            f"FY{rec['fiscal_year']}: allocations {total_alloc} != coverover {rec['coverover_amount_pr']}"
        )


def test_rum_known_coverover_rate_matches():
    for rec in KNOWN_COVEROVER:
        expected_tax = rec["rum_proof_gallons_pr"] * rec["excise_tax_rate_per_proof_gallon"]
        assert abs(expected_tax - rec["excise_tax_estimated"]) < 1000, (
            f"FY{rec['fiscal_year']}: excise tax mismatch"
        )


def test_rum_proof_gallons_double_regular():
    for rec in KNOWN_COVEROVER:
        assert rec["rum_proof_gallons_pr"] == rec["rum_gallons_pr"] * 2, (
            f"FY{rec['fiscal_year']}: proof gallons should be 2× regular gallons"
        )


# --- FHLB ---
from scripts.download_fhlb import (
    FHLB_COLUMNS,
    PR_FDIC_CERTS,
    _normalize_name as fhlb_normalize,
)


def test_fhlb_columns_complete():
    for col in ("institution_name", "institution_normalized", "fdic_cert",
                "reporting_date", "advances_outstanding"):
        assert col in FHLB_COLUMNS


def test_fhlb_pr_certs_include_banco_popular():
    names = list(PR_FDIC_CERTS.values())
    assert any("BANCO POPULAR" in n for n in names)


def test_fhlb_pr_certs_include_firstbank():
    names = list(PR_FDIC_CERTS.values())
    assert any("FIRSTBANK" in n or "FIRST" in n for n in names)


def test_fhlb_normalize_strips_bank():
    result = fhlb_normalize("Banco Popular de Puerto Rico N.A.")
    assert "N.A" not in result
    assert "BANCO POPULAR" in result or "POPULAR" in result


def test_fhlb_certs_are_numeric_strings():
    for cert in PR_FDIC_CERTS:
        assert cert.isdigit(), f"FDIC cert '{cert}' should be all digits"


def test_fhlb_advance_type_in_columns():
    assert "advance_type" in FHLB_COLUMNS
    assert "collateral_type" in FHLB_COLUMNS


# --- PREPA contracts ---
from scripts.download_prepa_contracts import (
    PREPA_COLUMNS,
    KNOWN_CONTRACTS,
    _normalize_name as prepa_normalize,
)


def test_prepa_columns_complete():
    for col in ("contract_id", "vendor_name", "vendor_normalized", "contract_type",
                "contract_value", "status"):
        assert col in PREPA_COLUMNS


def test_prepa_known_contracts_has_luma():
    names = [c["vendor_name"] for c in KNOWN_CONTRACTS]
    assert any("Luma" in n for n in names)


def test_prepa_known_contracts_has_genera():
    names = [c["vendor_name"] for c in KNOWN_CONTRACTS]
    assert any("Genera" in n for n in names)


def test_prepa_known_contracts_has_whitefish():
    names = [c["vendor_name"] for c in KNOWN_CONTRACTS]
    assert any("Whitefish" in n for n in names)


def test_prepa_luma_contract_value_over_1b():
    luma = next(c for c in KNOWN_CONTRACTS if "Luma" in c["vendor_name"] and c["contract_type"] == "O&M")
    assert luma["contract_value"] >= 1_000_000_000


def test_prepa_genera_contract_value_over_3b():
    genera = next(c for c in KNOWN_CONTRACTS if "Genera" in c["vendor_name"])
    assert genera["contract_value"] >= 3_000_000_000


def test_prepa_whitefish_status_terminated():
    wf = next(c for c in KNOWN_CONTRACTS if "Whitefish" in c["vendor_name"])
    assert wf["status"] == "Terminated"


def test_prepa_normalize_strips_llc():
    result = prepa_normalize("Luma Energy LLC")
    assert "LLC" not in result
    assert "LUMA ENERGY" in result


def test_prepa_known_contracts_have_source_url():
    for c in KNOWN_CONTRACTS:
        assert c.get("source_url", "").startswith("http"), f"Missing source_url: {c['contract_id']}"


# ---------------------------------------------------------------------------
# Group D — PROMESA creditors
# ---------------------------------------------------------------------------

from scripts.download_promesa_creditors import (
    PROMESA_COLUMNS,
    KNOWN_CREDITORS,
    _normalize_name as promesa_normalize,
)


def test_promesa_columns_complete():
    for col in ("creditor_name", "creditor_normalized", "creditor_type",
                "bond_series", "claim_amount_original", "recovery_amount", "recovery_rate"):
        assert col in PROMESA_COLUMNS


def test_promesa_known_creditors_non_empty():
    assert len(KNOWN_CREDITORS) >= 10


def test_promesa_has_hedge_funds():
    types = {c["creditor_type"] for c in KNOWN_CREDITORS}
    assert "hedge_fund" in types


def test_promesa_has_insurers():
    types = {c["creditor_type"] for c in KNOWN_CREDITORS}
    assert "insurer" in types


def test_promesa_has_mutual_funds():
    types = {c["creditor_type"] for c in KNOWN_CREDITORS}
    assert "mutual_fund" in types


def test_promesa_bond_series_covered():
    series = {c["bond_series"] for c in KNOWN_CREDITORS}
    for expected in ("GO", "COFINA", "PREPA"):
        assert expected in series, f"Missing bond series: {expected}"


def test_promesa_recovery_rates_between_0_and_1():
    for c in KNOWN_CREDITORS:
        rate = c.get("recovery_rate", 0)
        assert 0.0 <= rate <= 1.0, f"Invalid recovery rate {rate} for {c['creditor_name']}"


def test_promesa_recovery_amount_less_than_claim():
    for c in KNOWN_CREDITORS:
        assert c["recovery_amount"] <= c["claim_amount_original"], (
            f"{c['creditor_name']}: recovery > claim"
        )


def test_promesa_recovery_rate_consistent():
    for c in KNOWN_CREDITORS:
        if c["claim_amount_original"] > 0:
            implied = c["recovery_amount"] / c["claim_amount_original"]
            assert abs(implied - c["recovery_rate"]) < 0.01, (
                f"{c['creditor_name']}/{c['bond_series']}: rate inconsistency"
            )


def test_promesa_normalize_removes_lp():
    result = promesa_normalize("Aurelius Capital Management LP")
    assert "LP" not in result
    assert "AURELIUS CAPITAL MANAGEMENT" in result


def test_promesa_assurance_guaranteed_insurer():
    assured = next(
        (c for c in KNOWN_CREDITORS if "Assured" in c["creditor_name"] and c["creditor_type"] == "insurer"),
        None,
    )
    assert assured is not None


def test_promesa_franklin_has_sec_flag():
    franklin = next(
        (c for c in KNOWN_CREDITORS if "Franklin" in c["creditor_name"]),
        None,
    )
    assert franklin is not None
    assert franklin["sec_13f_flag"] == 1


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _make_logger():
    import logging
    logger = logging.getLogger("test_logger")
    logger.setLevel(logging.CRITICAL)
    return logger
