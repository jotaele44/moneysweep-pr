import json
from pathlib import Path

from scripts.check_network_egress import check_https_endpoint, run_checks
from scripts.build_source_recovery_matrix import build_rows, build_summary

_ROOT = Path(__file__).resolve().parents[1]


def test_materialization_runbook_exists_and_names_automatable_target():
    path = _ROOT / "docs" / "MATERIALIZATION_RUNBOOK.md"
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert "automatable" in text
    assert "reports/materialization_readiness.json" in text
    assert "coverage_rate" in text


def test_materialization_operator_checklist_exists():
    path = _ROOT / "docs" / "MATERIALIZATION_OPERATOR_CHECKLIST.md"
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert "Pre-Run Checklist" in text
    assert "Run Checklist" in text
    assert "Post-Run Checklist" in text
    assert "No secrets are committed" in text


def test_materialization_readiness_snapshot_matches_runbook_counts():
    snapshot = json.loads(
        (_ROOT / "reports" / "materialization_readiness.json").read_text(encoding="utf-8")
    )

    # 13 formerly scraper_needed sources promoted to api_producer after confirming
    # their producer scripts are importable with real scraping implementations.
    # Only hacienda_sut_ivu and pr_act_154_excise remain scraper_needed (true stubs).
    # Counts below are pinned to the regenerated reports/materialization_readiness.json.
    # total_sources / queued_excluded_total incremented by 1 for sba_disaster_loans_pr
    # (manual_export, queued pending an operator file drop).
    # oficina_contralor promoted manual_export -> api_producer: it now scrapes
    # iapconsulta.ocpr.gov.pr's live search API (scripts/scrape_iapconsulta.py)
    # instead of waiting on an operator export.
    # ocpr_contracts promoted manual_export -> api_producer: it now scrapes
    # consultacontratos.ocpr.gov.pr's live search API
    # (scripts/scrape_ocpr_contracts.py) instead of waiting on an operator
    # export.
    # centinelas_pre_official_signals added (automatable, on-drop pre-official
    # intake via scripts/ingest_centinelas_signals.py): total_sources and
    # automatable_total/automatable_ready each incremented by 1.
    # sam_opportunities added (automatable via SAM_API_KEY, pre-award federal
    # solicitations / bid notices; scripts/download_sam_opportunities.py):
    # total_sources and automatable_total/automatable_ready each incremented by 1.
    # RoadWatch corridor overlay promoted from
    # registries/source_registry_overlays/roadwatch_corridor_mapping.yaml into the
    # live registry: +5 total_sources. fhwa_hpms_routes, fhwa_nbi_bridges and
    # roadwatch_corridor_join are api_producer (+3 automatable_total/ready);
    # dtop_centerline_lrs and stip_tip_projects are manual_export
    # (+2 queued_excluded_total, awaiting operator drops).
    # asg_emergency_purchases and asg_suppliers added, both api_producer with live
    # HTML scrapers over asg.pr.gov (scripts/scrape_asg_emergency_purchases.py and
    # scripts/scrape_asg_suppliers.py): +2 total_sources and
    # +2 automatable_total/automatable_ready.
    # act_transition_ppp extracts P3 concession contracts from the committed
    # ACT/ACUDEN transition workbook, so it is automatable with no operator drop
    # (+1 total_sources, +1 automatable_total/automatable_ready).
    # prasa_completed_projects_ppp and prasa_consulting_engineer_ppp are
    # manual_export and blocked on files that are not in the repository
    # (+2 total_sources, +2 queued_excluded_total).
    # campaign-finance completion adds one live OCE source plus two derived
    # campaign-finance producers, all automatable after upstream refreshes
    # (+3 total_sources, +3 automatable_total/ready).
    # rdc_demandas_civiles added (api_producer, live HTML scraper over the
    # Registro de Demandas Civiles at justicia1.justicia.pr.gov/rdc;
    # scripts/scrape_rdc_demandas.py): +1 total_sources and
    # +1 automatable_total/automatable_ready. Its detail-enrichment pass
    # (scripts/enrich_rdc_details.py) is a second stage of the same source, not
    # a separate registry entry, so it adds nothing to these counts.
    # hacienda_sut_ivu promoted scraper_needed -> api_producer: it now parses the
    # live monthly IVU/SUT distribution PDFs from hacienda.pr.gov
    # (scripts/download_hacienda_sut_ivu.py) instead of waiting on a scraping
    # adapter. +1 automatable_total/automatable_ready, -1 queued_excluded_total
    # (scraper_needed 2 -> 1). Only pr_act_154_excise remains scraper_needed.
    live = build_summary(build_rows())
    assert snapshot["total_sources"] == live["total_sources"]
    assert snapshot["automatable_total"] == live["automatable_total"]
    assert snapshot["automatable_ready"] == live["automatable_ready"]
    assert snapshot["queued_excluded_total"] == live["queued_excluded_total"]
    assert snapshot["automatable_not_ready"] == []


def test_egress_checker_invalid_url_fails_without_network():
    result = check_https_endpoint("http://not-https.example")
    assert result.ok is False
    assert result.error == "invalid https url"


def test_egress_checker_run_checks_reports_blocked_for_invalid_endpoint():
    result = run_checks(["http://not-https.example"])
    assert result["ok"] is False
    assert len(result["checked"]) == 1
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["error"] == "invalid https url"
