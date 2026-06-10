"""Tests for the financial-flows master -> export-stream bridge."""

from pathlib import Path

import pandas as pd
import pytest

from scripts.build_financial_flows_master import _finalize_flow_frame, run
from scripts.parquet_utils import pq_read


@pytest.mark.unit
def test_finalize_flow_frame_derives_flow_date_by_precedence():
    df = pd.DataFrame(
        [
            {
                "flow_id": "drawdown-first",
                "amount": "100",
                "flow_date": "",
                "drawdown_date": "2024-03-04",
                "obligation_date": "2024-02-03",
                "award_date": "2024-01-02",
            },
            {
                "flow_id": "obligation-second",
                "amount": "200",
                "flow_date": "",
                "drawdown_date": "",
                "obligation_date": "2024-05-06",
                "award_date": "2024-04-05",
            },
            {
                "flow_id": "award-third",
                "amount": "300",
                "flow_date": "",
                "drawdown_date": "",
                "obligation_date": "",
                "award_date": "2024-07-08",
            },
            {
                "flow_id": "explicit-wins",
                "amount": "400",
                "flow_date": "2024-09-10",
                "drawdown_date": "2024-08-09",
                "obligation_date": "2024-07-08",
                "award_date": "2024-06-07",
            },
        ]
    )

    out = _finalize_flow_frame(df)

    assert list(out["flow_date"]) == [
        "2024-03-04",
        "2024-05-06",
        "2024-07-08",
        "2024-09-10",
    ]
    assert "recipient_entity_id" in out.columns


@pytest.mark.unit
def test_run_writes_processed_csv_bridge_with_flow_date(tmp_path):
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    (processed / "pr_contracts_master.csv").write_text(
        "award_id,recipient_name,recipient_uei,obligated_amount,award_date,pop_county,source_dataset\n"
        "AWD-1,ACME Construction,ACME123UEI,125000.00,2024-02-03,San Juan,usaspending_prime\n",
        encoding="utf-8",
    )

    result = run(root=tmp_path, force=True)

    assert result["status"] == "OK"
    assert result["rows"] == 1

    parquet_master = tmp_path / "data" / "normalized" / "financial_flows_master.parquet"
    df_master = pq_read(parquet_master)
    assert len(df_master) == 1
    assert df_master.iloc[0]["flow_date"] == "2024-02-03"
    assert df_master.iloc[0]["recipient_entity_id"] == "ACME123UEI"

    csv_bridge = processed / "financial_flows_master.csv"
    assert csv_bridge.exists()
    df_bridge = pd.read_csv(csv_bridge, dtype=str)
    assert len(df_bridge) == 1
    assert df_bridge.iloc[0]["flow_date"] == "2024-02-03"
    assert df_bridge.iloc[0]["recipient_entity_id"] == "ACME123UEI"
