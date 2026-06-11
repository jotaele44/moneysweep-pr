"""Smoke tests for downloader scripts wired in from archive/ (staged PRs B1-B6).

Each batch un-archives a family of optional source producers. These tests confirm
the modules import cleanly, expose a callable run(), and that the registry points
their source(s) at the live scripts/ path. They do not exercise network calls.
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.source_registry import source_by_id

# (source_id, producer module basename) — extended as each B-batch lands.
B1_FEDERAL_GRANTS = [
    ("ed_grants", "download_ed"),
    ("hhs_grants", "download_hhs"),
    ("doj_grants", "download_doj_grants"),
    ("oia_grants", "download_oia"),
    ("epa_grants", "download_epa"),
    ("dot_grants", "download_dot"),
    ("usda_grants", "download_usda"),
    ("doe_grants", "download_doe"),
    ("research_grants", "download_research"),
    ("grants_gov", "download_grants"),
    ("fpds_report_builder", "download_grants"),
]

B2_BENEFITS_HEALTH = [
    ("chip", "download_chip"),
    ("cms_open_payments", "download_cms"),
    ("medicaid_fmap", "download_medicaid_fmap"),
    ("medicare_parts", "download_medicare_parts"),
    ("medicare_advantage", "download_medicare_advantage"),
    ("ssa", "download_ssa"),
    ("va_benefits", "download_va"),
    ("wic", "download_wic"),
    ("wioa", "download_wioa"),
    ("snap_nap", "download_snap_nap"),
    ("dol_whd_osha", "download_dol"),
]

B3_FEDERAL_FINANCIAL = [
    ("fdic", "download_fdic"),
    ("ncua", "download_ncua"),
    ("fhlb", "download_fhlb"),
    ("sec_edgar", "download_sec"),
    ("sec_13f_nport", "download_sec_holdings"),
    ("exim_bank", "download_exim"),
    ("sba_loans", "download_sba"),
    ("sba_ppp", "download_sba"),
    ("sbir", "download_sbir"),
]

B4_DISASTER_RESEARCH = [
    ("fema_hmgp", "download_fema"),
    ("haf", "download_haf"),
    ("slfrf", "download_slfrf"),
    ("nfip_claims", "download_nfip"),
    ("lihtc", "download_lihtc"),
    ("nmtc", "download_nmtc"),
    ("usace_civil_works", "download_usace_civil"),
    ("usace_permits", "download_usace_permits"),
    ("hud_hcv_section8", "download_hud_hcv"),
    ("congressional_earmarks", "download_earmarks"),
    ("sf133_budget_execution", "download_sf133"),
    ("fcc_usf", "download_fcc"),
    ("nih_reporter", "download_nih"),
    ("gao_ig_audits", "download_gao_ig"),
    ("nonprofits_irs990", "download_nonprofits"),
]

B5_TERRITORIAL_MUNICIPAL = [
    ("aafaf", "download_aafaf"),
    ("hacienda", "download_hacienda"),
    ("cofina", "download_cofina"),
    ("promesa_creditors", "download_promesa_creditors"),
    ("pr_act_60_decrees", "download_act60"),
    ("p3_authority", "download_p3"),
    ("pr_pensions", "download_pr_pensions"),
    ("rum_cover_over", "download_rum_coverover"),
    ("municipal_finance", "download_municipal"),
    ("eqb_epa_icis", "download_eqb"),
    ("compras_pr", "download_compras"),
    ("prepa_luma_genera", "download_prepa_contracts"),
]

B6_BONDS_ENTITY_MANUAL = [
    ("msrb_rtrs_trades", "download_msrb_trades"),
    ("ofac_sdn", "download_ofac"),
    ("dcaa_active_contractors", "download_active_contractors"),
]

# Free, keyless entity-resolution sources that replace the paid OpenCorporates.
B7_FREE_ENTITY_RESOLUTION = [
    ("gleif_lei", "download_gleif"),
    ("sec_officers", "download_sec_officers"),
]

WIRED_SOURCES = (
    B1_FEDERAL_GRANTS
    + B2_BENEFITS_HEALTH
    + B3_FEDERAL_FINANCIAL
    + B4_DISASTER_RESEARCH
    + B5_TERRITORIAL_MUNICIPAL
    + B6_BONDS_ENTITY_MANUAL
    + B7_FREE_ENTITY_RESOLUTION
)


@pytest.mark.parametrize("source_id,module", WIRED_SOURCES)
def test_wired_producer_imports_and_runs(source_id, module):
    mod = importlib.import_module(f"scripts.{module}")
    assert callable(getattr(mod, "run", None)), f"{module}: missing callable run()"


@pytest.mark.parametrize("source_id,module", WIRED_SOURCES)
def test_wired_registry_points_to_scripts(source_id, module):
    src = source_by_id(source_id)
    assert src is not None, f"{source_id}: not in registry"
    assert src["producer_script"] == f"scripts/{module}.py", (
        f"{source_id}: producer_script {src['producer_script']!r} not wired to scripts/"
    )
