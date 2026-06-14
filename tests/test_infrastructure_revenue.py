"""Tests for the infrastructure revenue/income subsystem.

Covers:
  - the shared revenue dropzone reader (scripts._revenue_common)
  - the shared contract dropzone reader (scripts._contract_dropzone)
  - the PRASA contracts master aggregator (closes a dangling registry output)
  - the revenue flow ingest that sets payer = aggregate public, payee = agency
  - the export layer deriving an inflow transaction_type from a revenue flow_type
  - registry integrity: every expected_output has a producer script on disk

All offline — the producers are dropzone readers, never live scrapers.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pandas as pd
import pytest

from contract_sweeper.runtime.source_registry import all_sources, expected_outputs_for
from scripts._revenue_common import REVENUE_COLUMNS, _parse_df as parse_revenue
from scripts._contract_dropzone import CONTRACT_COLUMNS, _parse_df as parse_contract
from scripts import ingest_toll_revenue, ingest_dtop_road_contracts, build_prasa_contracts_master
from scripts.build_financial_flows_master import _ingest_infrastructure_revenue
from scripts.build_export_streams import _transaction_type_for, build_streams

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INPUTS = REPO_ROOT / "tests" / "fixtures" / "sample_master_inputs"
GENERATED_AT = "2024-01-15T12:00:00Z"


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


# ---------------------------------------------------------------------------
# Revenue dropzone reader
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_revenue_parse_maps_spanish_headers_and_tags_domain():
    df = pd.DataFrame(
        {
            "Año Fiscal": ["2023", "2024"],
            "Concepto": ["Peajes AutoExpreso", "Peajes Metropistas"],
            "Monto": ["$120,000,000", "85000000"],
        }
    )
    out = parse_revenue(df, "toll_2024.csv", "toll", "AUTORIDAD DE CARRETERAS", _NullLogger())
    assert list(out.columns) == REVENUE_COLUMNS
    assert len(out) == 2
    assert out.iloc[0]["service_domain"] == "toll"
    assert out.iloc[0]["collecting_agency"] == "AUTORIDAD DE CARRETERAS"
    assert out.iloc[0]["amount"] == "120000000"  # punctuation stripped
    assert out.iloc[0]["currency"] == "USD"
    assert out.iloc[0]["source_file"] == "toll_2024.csv"


@pytest.mark.unit
def test_revenue_parse_drops_rows_without_amount():
    df = pd.DataFrame({"Concepto": ["A", "B"], "Monto": ["1000", ""]})
    out = parse_revenue(df, "f.csv", "utility", "PRASA", _NullLogger())
    assert len(out) == 1


@pytest.mark.integration
def test_toll_revenue_run_materializes_from_dropzone(tmp_path: Path):
    drop = tmp_path / "data" / "manual" / "act_toll_revenue"
    drop.mkdir(parents=True)
    with (drop / "toll.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fiscal_year", "revenue_category", "amount"])
        w.writerow(["2024", "AutoExpreso", "120000000"])

    result = ingest_toll_revenue.run(root=tmp_path)
    assert result["rows"] == 1
    out = tmp_path / "data" / "staging" / "processed" / "pr_act_toll_revenue.csv"
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[0]["service_domain"] == "toll"
    assert rows[0]["amount"] == "120000000"


@pytest.mark.integration
def test_revenue_run_no_dropzone_writes_empty_header(tmp_path: Path):
    result = ingest_toll_revenue.run(root=tmp_path)
    assert result["rows"] == 0
    out = tmp_path / "data" / "staging" / "processed" / "pr_act_toll_revenue.csv"
    assert out.exists()
    assert list(csv.DictReader(out.open(encoding="utf-8"))) == []


# ---------------------------------------------------------------------------
# Contract dropzone reader + PRASA master
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_contract_parse_maps_headers_and_normalizes_vendor():
    df = pd.DataFrame(
        {
            "Contratista": ["Acme LLC"],
            "Número de Contrato": ["DT-24-01"],
            "Monto": ["3000000"],
        }
    )
    out = parse_contract(df, "roads.csv", "DTOP", _NullLogger())
    assert list(out.columns) == CONTRACT_COLUMNS
    assert out.iloc[0]["vendor_normalized"] == "ACME"
    assert out.iloc[0]["agency"] == "DTOP"


@pytest.mark.integration
def test_dtop_contracts_run_materializes(tmp_path: Path):
    drop = tmp_path / "data" / "manual" / "dtop_road_contracts"
    drop.mkdir(parents=True)
    with (drop / "c.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vendor_name", "contract_value", "award_date"])
        w.writerow(["Roadbuilders Inc", "5000000", "2024-03-01"])
    result = ingest_dtop_road_contracts.run(root=tmp_path)
    assert result["rows"] == 1


@pytest.mark.integration
def test_prasa_master_aggregates_vendors(tmp_path: Path):
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True)
    with (proc / "pr_prasa_contracts.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["vendor_normalized", "vendor_name", "contract_value", "award_date", "source_file"]
        )
        w.writerow(["ACME", "Acme LLC", "1000000", "2023-01-01", "p.csv"])
        w.writerow(["ACME", "Acme LLC", "500000", "2024-01-01", "p.csv"])
        w.writerow(["BETA", "Beta Corp", "250000", "2022-06-01", "p.csv"])
    result = build_prasa_contracts_master.run(root=tmp_path)
    assert result["rows"] == 2
    out = proc / "prasa_contracts_master.csv"
    by_vendor = {r["vendor_normalized"]: r for r in csv.DictReader(out.open(encoding="utf-8"))}
    assert by_vendor["ACME"]["contract_count"] == "2"
    assert float(by_vendor["ACME"]["total_contract_value"]) == 1500000.0


# ---------------------------------------------------------------------------
# Direction + transaction_type (the income-modeling core)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_transaction_type_for_revenue_and_default():
    assert _transaction_type_for({"flow_type": "toll_revenue"}) == "toll_collection"
    assert _transaction_type_for({"flow_type": "fare_revenue"}) == "fare_collection"
    assert _transaction_type_for({"flow_type": "port_fee_revenue"}) == "port_fee_revenue"
    assert _transaction_type_for({"flow_type": "federal_contract"}) == "disbursement"
    assert _transaction_type_for({}) == "disbursement"
    # explicit column wins
    assert _transaction_type_for({"transaction_type": "utility_rate_revenue"}) == (
        "utility_rate_revenue"
    )


@pytest.mark.unit
def test_revenue_flow_ingest_sets_public_payer_and_agency_payee():
    df = pd.DataFrame(
        {
            "fiscal_year": ["2024"],
            "service_domain": ["toll"],
            "collecting_agency": ["AUTORIDAD DE CARRETERAS Y TRANSPORTACION"],
            "revenue_category": ["AutoExpreso"],
            "amount": ["120000000"],
            "currency": ["USD"],
            "source_type": [""],
            "pledged_debt_ref": [""],
            "municipality": [""],
            "source_file": ["toll.csv"],
        }
    )
    rows = _ingest_infrastructure_revenue([("act_toll_revenue", "toll.csv", df)], _NullLogger())
    assert len(rows) == 1
    r = rows[0]
    assert r["flow_type"] == "toll_revenue"
    assert r["funding_source"] == "PUBLIC RATEPAYERS TOLL"  # payer = aggregate public
    assert r["responsible_organization"] == "AUTORIDAD DE CARRETERAS Y TRANSPORTACION"  # payee
    assert r["amount_type"] == "gross_revenue"
    assert r["amount"] == "120000000"


@pytest.mark.integration
def test_export_emits_revenue_transaction_with_public_payer(tmp_path: Path):
    """End-to-end: a revenue flow row becomes a schema-valid inflow transaction."""
    inputs = tmp_path / "inputs"
    shutil.copytree(SAMPLE_INPUTS, inputs)

    flows_path = inputs / "financial_flows_master.csv"
    existing = list(csv.DictReader(flows_path.open(encoding="utf-8")))
    fieldnames = list(existing[0].keys()) + ["flow_type"]
    for row in existing:
        row["flow_type"] = "federal_contract"
    existing.append(
        {
            **{k: "" for k in fieldnames},
            "flow_id": "FL-REV-1",
            "funding_source": "PUBLIC RATEPAYERS TOLL",
            "recipient_entity_id": "ACME123UEI",  # resolvable payee stand-in
            "amount": "500000.00",
            "flow_date": "2024-02-01",
            "source_system": "usaspending_prime",
            "source_file": "pr_act_toll_revenue.csv",
            "link_confidence": "0.9",
            "flow_type": "toll_revenue",
        }
    )
    with flows_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(existing)

    staging = tmp_path / "streams"
    build_streams(inputs, staging, generated_at=GENERATED_AT)

    import json

    txns = [
        json.loads(line)
        for line in (staging / "transactions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    revenue = [t for t in txns if t["transaction_type"] == "toll_collection"]
    assert len(revenue) == 1
    assert revenue[0]["amount"] == 500000.0

    entities = {
        json.loads(line)["entity_id"]: json.loads(line)["normalized_name"]
        for line in (staging / "entities.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert entities[revenue[0]["payer_entity_id"]] == "PUBLIC RATEPAYERS TOLL"


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_expected_output_has_a_producer_on_disk():
    """Each expected_output must be backed by a producer script that exists.

    Would have caught the previously-dangling prasa_contracts_master.csv output.
    """
    missing = []
    for src in all_sources(REPO_ROOT):
        producer = REPO_ROOT / str(src.get("producer_script", ""))
        outs = expected_outputs_for(src, REPO_ROOT)
        if outs and not producer.exists():
            missing.append((src["source_id"], src.get("producer_script")))
    assert not missing, f"sources with expected_outputs but no producer on disk: {missing}"
