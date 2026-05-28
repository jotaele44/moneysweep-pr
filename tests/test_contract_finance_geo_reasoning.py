"""Tests for the row-level contract-finance geo reasoning producer."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.run_contract_finance_geo_reasoning import (
    DENSITY_COLUMNS,
    EDGE_METADATA_FIELDS,
    GEO_RESOLUTION_REASONS,
    JURISDICTION_CLASSES,
    Crosswalk,
    build_crosswalk_rows,
    classify_geo,
    run,
    write_crosswalk,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MUNI_REF = REPO_ROOT / "data" / "reference" / "pr_municipalities.csv"


# --------------------------------------------------------------------------- #
# Crosswalk (Task 4)                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_crosswalk_has_78_rows_with_unique_codes():
    rows = build_crosswalk_rows(MUNI_REF)
    assert len(rows) == 78
    codes = [r["municipality_code"] for r in rows]
    assert len(set(codes)) == 78
    assert all(c.startswith("72") and len(c) == 5 for c in codes)
    # geoid mirrors the 5-digit county-FIPS code.
    assert all(r["municipality_geoid"] == r["municipality_code"] for r in rows)


@pytest.mark.unit
@pytest.mark.parametrize(
    "accented,ascii_form",
    [
        ("BAYAMÓN", "BAYAMON"),
        ("MAYAGÜEZ", "MAYAGUEZ"),
        ("GUÁNICA", "GUANICA"),
        ("RINCÓN", "RINCON"),
        ("SAN GERMÁN", "SAN GERMAN"),
        ("RÍO GRANDE", "RIO GRANDE"),
        ("CATAÑO", "CATANO"),
        ("LOÍZA", "LOIZA"),
        ("PEÑUELAS", "PENUELAS"),
        ("AÑASCO", "ANASCO"),
        ("COMERÍO", "COMERIO"),
        ("LAS MARÍAS", "LAS MARIAS"),
    ],
)
def test_crosswalk_collapses_accent_ascii_aliases(tmp_path, accented, ascii_form):
    path = tmp_path / "cw.csv"
    write_crosswalk(path, MUNI_REF)
    cw = Crosswalk.load(path)
    code_accented = cw.resolve_name(accented)
    code_ascii = cw.resolve_name(ascii_form)
    assert code_accented != ""
    assert code_accented == code_ascii


# --------------------------------------------------------------------------- #
# Per-row classification (Task 3)                                             #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def crosswalk(tmp_path_factory):
    path = tmp_path_factory.mktemp("ref") / "cw.csv"
    write_crosswalk(path, MUNI_REF)
    return Crosswalk.load(path)


def _classify(crosswalk, **geo):
    return classify_geo(geo, crosswalk)


@pytest.mark.unit
def test_place_of_performance_exact(crosswalk):
    r = _classify(crosswalk, raw_code="72127", raw_name="San Juan", attribution_source="place_of_performance")
    assert r["geo_resolution_reason"] == "place_of_performance_exact"
    assert r["jurisdiction_class"] == "PR_MUNICIPIO"
    assert r["municipality_code_canonical"] == "72127"
    assert r["unknown_reason"] == ""


@pytest.mark.unit
def test_recipient_municipality_match(crosswalk):
    r = _classify(crosswalk, raw_code="72113", attribution_source="recipient_address")
    assert r["geo_resolution_reason"] == "recipient_municipality_match"
    assert r["jurisdiction_class"] == "PR_MUNICIPIO"


@pytest.mark.unit
def test_project_municipality_match(crosswalk):
    r = _classify(crosswalk, raw_code="72003", attribution_source="project_municipality")
    assert r["geo_resolution_reason"] == "project_municipality_match"


@pytest.mark.unit
def test_headquarters_only_sets_hq_and_jurisdiction(crosswalk):
    r = _classify(crosswalk, raw_code="72127", attribution_source="headquarters")
    assert r["geo_resolution_reason"] == "headquarters_only"
    assert r["jurisdiction_class"] == "HEADQUARTERS_ONLY"
    assert r["hq_bias_flag"] is True
    assert r["san_juan_bias_flag"] is True  # San Juan + HQ source
    assert r["unknown_reason"] == "headquarters_only"


@pytest.mark.unit
def test_agency_default(crosswalk):
    r = _classify(crosswalk, raw_code="72127", attribution_source="funding_office")
    assert r["geo_resolution_reason"] == "agency_default"
    assert r["jurisdiction_class"] == "AGENCY_DEFAULT"
    assert r["san_juan_bias_flag"] is True


@pytest.mark.unit
def test_municipality_name_only(crosswalk):
    r = _classify(crosswalk, raw_name="Mayagüez")
    assert r["geo_resolution_reason"] == "municipality_name_only"
    assert r["jurisdiction_class"] == "PR_MUNICIPIO"
    assert r["municipality_code_canonical"] == "72097"


@pytest.mark.unit
def test_missing_location(crosswalk):
    r = _classify(crosswalk)
    assert r["geo_resolution_reason"] == "missing_location"
    assert r["jurisdiction_class"] == "UNKNOWN_MISSING"
    assert r["unknown_reason"] == "missing_location"


@pytest.mark.unit
def test_ambiguous_location(crosswalk):
    r = _classify(crosswalk, raw_name="Nowhere City")
    assert r["geo_resolution_reason"] == "ambiguous_location"
    assert r["jurisdiction_class"] == "UNKNOWN_AMBIGUOUS"


@pytest.mark.unit
def test_invalid_pr_municipio_never_kept_as_pr(crosswalk):
    # 72999 has the PR prefix but is not one of the 78 municipios.
    r = _classify(crosswalk, raw_code="72999")
    assert r["geo_resolution_reason"] == "invalid_pr_municipio"
    assert r["jurisdiction_class"] != "PR_MUNICIPIO"
    assert r["municipality_code_canonical"] == ""


@pytest.mark.unit
def test_outside_pr_us_county_by_fips(crosswalk):
    r = _classify(crosswalk, raw_code="36061")  # New York County, NY
    assert r["geo_resolution_reason"] == "outside_pr"
    assert r["jurisdiction_class"] == "OUTSIDE_PR_US_COUNTY"
    assert r["outside_pr_flag"] is True


@pytest.mark.unit
def test_outside_pr_us_state(crosswalk):
    r = _classify(crosswalk, raw_name="Miami", state="FL")
    assert r["geo_resolution_reason"] == "outside_pr"
    assert r["jurisdiction_class"] == "OUTSIDE_PR_US_STATE"


@pytest.mark.unit
def test_outside_pr_foreign(crosswalk):
    r = _classify(crosswalk, raw_name="Santo Domingo", country="DO")
    assert r["jurisdiction_class"] == "OUTSIDE_PR_FOREIGN"


@pytest.mark.unit
def test_all_reasons_and_classes_are_in_vocabulary(crosswalk):
    samples = [
        dict(raw_code="72127", attribution_source="place_of_performance"),
        dict(raw_code="72999"),
        dict(raw_name="Miami", state="FL"),
        dict(),
    ]
    for s in samples:
        r = classify_geo(s, crosswalk)
        assert r["geo_resolution_reason"] in GEO_RESOLUTION_REASONS
        assert r["jurisdiction_class"] in JURISDICTION_CLASSES


# --------------------------------------------------------------------------- #
# End-to-end pipeline (Tasks 5-9)                                             #
# --------------------------------------------------------------------------- #

def _write_master(path: Path, header: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


@pytest.fixture
def synthetic_inputs(tmp_path):
    processed = tmp_path / "processed"
    contracts_header = [
        "award_id", "recipient_name", "normalized_name", "awarding_agency",
        "obligation_amount", "award_date", "fiscal_year", "municipality",
        "geo_municipality_code", "geo_municipality_name", "geo_county_fips",
        "geo_attribution_source", "geo_attribution_confidence", "source_system",
    ]
    contracts = [
        # Clean PR place-of-performance.
        dict(award_id="A1", recipient_name="Acme", awarding_agency="FEMA",
             obligation_amount="1000000", award_date="2023-01-01", fiscal_year="2023",
             geo_municipality_code="72127", geo_municipality_name="San Juan",
             geo_attribution_source="place_of_performance", geo_attribution_confidence="0.97",
             source_system="usaspending"),
        # San Juan HQ bias row.
        dict(award_id="A2", recipient_name="Beta", awarding_agency="FEMA",
             obligation_amount="200000", award_date="2023-02-01", fiscal_year="2023",
             geo_municipality_code="72127", geo_municipality_name="San Juan",
             geo_attribution_source="headquarters", geo_attribution_confidence="0.5",
             source_system="usaspending"),
        # Missing location.
        dict(award_id="A3", recipient_name="Gamma", awarding_agency="DoD",
             obligation_amount="50000", award_date="2023-03-01", fiscal_year="2023",
             source_system="fpds"),
        # False PR municipio code.
        dict(award_id="A4", recipient_name="Delta", awarding_agency="DoD",
             obligation_amount="25000", award_date="2023-04-01", fiscal_year="2023",
             geo_municipality_code="72999", source_system="fpds"),
    ]
    _write_master(processed / "contracts_master.csv", contracts_header, contracts)

    flows_header = [
        "flow_id", "funding_source", "recipient_entity_id", "amount", "flow_date",
        "municipality", "geo_municipality_code", "geo_municipality_name",
        "geo_attribution_confidence", "source_system",
    ]
    flows = [
        dict(flow_id="F1", funding_source="FEMA", recipient_entity_id="Acme",
             amount="300000", flow_date="2023-05-01", geo_municipality_code="72097",
             geo_municipality_name="Mayaguez", geo_attribution_confidence="0.9",
             source_system="usaspending"),
    ]
    _write_master(processed / "financial_flows_master.csv", flows_header, flows)
    return processed


@pytest.mark.integration
def test_pipeline_produces_all_outputs(tmp_path, synthetic_inputs):
    out = tmp_path / "out"
    result = run(
        processed_dir=synthetic_inputs,
        output_dir=out,
        crosswalk_path=tmp_path / "cw.csv",
        build_crosswalk=True,
    )
    expected = [
        "contract_finance_geo_rows.csv",
        "unknown_decomposition.csv",
        "unknown_decomposition_summary.json",
        "san_juan_hq_bias_report.csv",
        "san_juan_hq_bias_summary.json",
        "municipality_funding_density.csv",
        "entity_graph.graphml",
        "entity_graph_edge_metadata_audit.csv",
        "entity_graph_qa_report.json",
        "spiderweb_engine_readiness_reassessment.json",
    ]
    for name in expected:
        assert (out / name).exists(), f"missing output {name}"
    assert result["row_count"] == 5


@pytest.mark.integration
def test_density_has_required_columns(tmp_path, synthetic_inputs):
    out = tmp_path / "out"
    run(processed_dir=synthetic_inputs, output_dir=out, crosswalk_path=tmp_path / "cw.csv", build_crosswalk=True)
    with (out / "municipality_funding_density.csv").open() as f:
        header = next(csv.reader(f))
    assert header == DENSITY_COLUMNS


@pytest.mark.integration
def test_unknown_decomposition_classifies_rows(tmp_path, synthetic_inputs):
    out = tmp_path / "out"
    run(processed_dir=synthetic_inputs, output_dir=out, crosswalk_path=tmp_path / "cw.csv", build_crosswalk=True)
    summary = json.loads((out / "unknown_decomposition_summary.json").read_text())
    by_reason = summary["by_reason"]
    assert "missing_location" in by_reason
    assert "invalid_pr_municipio" in by_reason
    assert summary["has_unclassified"] is False


@pytest.mark.integration
def test_san_juan_bias_flags_hq_row(tmp_path, synthetic_inputs):
    out = tmp_path / "out"
    run(processed_dir=synthetic_inputs, output_dir=out, crosswalk_path=tmp_path / "cw.csv", build_crosswalk=True)
    summary = json.loads((out / "san_juan_hq_bias_summary.json").read_text())
    assert summary["biased_record_count"] == 1  # the A2 headquarters row
    rows = list(csv.DictReader((out / "san_juan_hq_bias_report.csv").open()))
    assert any(r["record_id"] == "A2" for r in rows)


@pytest.mark.integration
def test_graphml_edges_carry_metadata(tmp_path, synthetic_inputs):
    import networkx as nx

    out = tmp_path / "out"
    run(processed_dir=synthetic_inputs, output_dir=out, crosswalk_path=tmp_path / "cw.csv", build_crosswalk=True)
    g = nx.read_graphml(out / "entity_graph.graphml")
    assert g.number_of_edges() > 0
    for _, _, data in g.edges(data=True):
        for field in EDGE_METADATA_FIELDS:
            assert field in data, f"edge missing metadata field {field}"
        json.loads(data["lineage"])  # lineage is valid JSON
    qa = json.loads((out / "entity_graph_qa_report.json").read_text())
    assert qa["zero_metadata_fields"] is False
    assert qa["edges_missing_lineage"] == 0
    assert qa["edges_missing_confidence"] == 0


@pytest.mark.integration
def test_readiness_gate_fails_on_false_pr_code(tmp_path, synthetic_inputs, monkeypatch):
    """Inject a row classified PR_MUNICIPIO with a code outside the 78-set and
    assert the gate's false-PR check trips."""
    import scripts.run_contract_finance_geo_reasoning as mod

    out = tmp_path / "out"
    real_classify = mod.classify_rows

    def poisoned(rows, crosswalk):
        enriched = real_classify(rows, crosswalk)
        if enriched:
            enriched[0]["jurisdiction_class"] = "PR_MUNICIPIO"
            enriched[0]["municipality_code_canonical"] = "72999"  # not a real municipio
        return enriched

    monkeypatch.setattr(mod, "classify_rows", poisoned)
    run(processed_dir=synthetic_inputs, output_dir=out, crosswalk_path=tmp_path / "cw.csv", build_crosswalk=True)
    readiness = json.loads((out / "spiderweb_engine_readiness_reassessment.json").read_text())
    assert readiness["passed"] is False
    false_pr = next(c for c in readiness["checks"] if c["check"] == "no_false_pr_municipio_code")
    assert false_pr["passed"] is False


@pytest.mark.integration
def test_readiness_gate_passes_on_clean_inputs(tmp_path, synthetic_inputs):
    out = tmp_path / "out"
    run(processed_dir=synthetic_inputs, output_dir=out, crosswalk_path=tmp_path / "cw.csv", build_crosswalk=True)
    readiness = json.loads((out / "spiderweb_engine_readiness_reassessment.json").read_text())
    recon = next(c for c in readiness["checks"] if c["check"] == "totals_reconciled")
    assert recon["passed"] is True
    assert readiness["passed"] is True
