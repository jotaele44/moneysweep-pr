import json

from scripts.produce_pr_news_raw_intake import main_with_args


def test_pr_news_raw_intake_producer_writes_router_ready_jsonl(tmp_path):
    input_path = tmp_path / "incoming.jsonl"
    output_path = tmp_path / "raw_items_latest.jsonl"
    manifest_path = tmp_path / "manifest.json"
    input_path.write_text(
        json.dumps(
            {
                "source_name": "Fortaleza",
                "source_url": "https://example.test/funding",
                "title": "Gobierno anuncia asignación de $5 millones",
                "summary": "Fondos para proyecto municipal",
                "municipality": "Ponce",
                "source_type": "official press release",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rc = main_with_args(["--input", str(input_path), "--output", str(output_path), "--manifest", str(manifest_path)])

    assert rc == 0
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["source_item_id"].startswith("PRNEWS-RAW-")
    assert row["summary_own_words"] == "Fondos para proyecto municipal"
    assert row["evidence_tier"] == "T2"
    assert row["confidence_level"] == "High"
    assert row["municipality_name"] == "Ponce"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["zero_loss_pass"] is True
    assert manifest["output_count"] == 1


def test_pr_news_raw_intake_missing_input_writes_empty_latest(tmp_path):
    input_path = tmp_path / "missing.jsonl"
    output_path = tmp_path / "raw_items_latest.jsonl"
    manifest_path = tmp_path / "manifest.json"

    rc = main_with_args(["--input", str(input_path), "--output", str(output_path), "--manifest", str(manifest_path)])

    assert rc == 0
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == ""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "missing_input"
    assert manifest["zero_loss_pass"] is True
