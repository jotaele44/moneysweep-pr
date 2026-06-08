import json

from scripts.run_pr_intake_router_hook import run


def test_pr_intake_router_hook_skips_missing_input(tmp_path):
    missing_input = tmp_path / "missing.jsonl"
    out_dir = tmp_path / "exports"

    assert run(missing_input, out_dir) == 0
    assert not out_dir.exists()


def test_pr_intake_router_hook_runs_existing_input(tmp_path):
    input_path = tmp_path / "raw_items.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "source_item_id": "RAW-HOOK-001",
                        "source_name": "Fortaleza",
                        "source_url": "https://example.test/funding",
                        "published_at": "2026-05-27",
                        "discovered_at": "2026-05-27T12:00:00Z",
                        "title": "Gobierno anuncia asignación de $5 millones",
                        "summary": "Fondos asignados por agencia pública.",
                    }
                ),
                json.dumps(
                    {
                        "source_item_id": "RAW-HOOK-002",
                        "source_name": "USGS",
                        "source_url": "https://example.test/lidar",
                        "published_at": "2026-05-27",
                        "discovered_at": "2026-05-27T12:00:00Z",
                        "title": "Nuevo dataset LiDAR de Puerto Rico",
                        "summary": "Dataset GIS con DEM.",
                        "location_text": "Puerto Rico",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "exports"

    assert run(input_path, out_dir, fail_on_validation_errors=True) == 0
    summary = json.loads((out_dir / "routing_summary.json").read_text(encoding="utf-8"))
    assert summary["zero_loss_pass"] is True
    assert summary["raw_item_count"] == 2
    assert summary["contract_sweeper_derivative_count"] == 1
    assert summary["spiderweb_pr_derivative_count"] == 1
