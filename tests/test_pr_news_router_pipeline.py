import json

from scripts.run_pr_news_router_pipeline import main_with_args, verify_exports


def test_pr_news_router_pipeline_writes_raw_intake_and_router_exports(tmp_path):
    incoming = tmp_path / "incoming_items_latest.jsonl"
    raw_output = tmp_path / "raw_items_latest.jsonl"
    manifest = tmp_path / "raw_items_latest_manifest.json"
    export_dir = tmp_path / "router_exports"

    incoming.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "source_name": "Fortaleza",
                        "source_url": "https://example.test/funding",
                        "published_at": "2026-05-27",
                        "title": "Gobierno anuncia asignación de $5 millones para proyecto municipal",
                        "summary": "Fondos asignados por agencia pública para reparación.",
                        "municipality": "Ponce",
                        "source_type": "official press release",
                    }
                ),
                json.dumps(
                    {
                        "source_name": "USGS",
                        "source_url": "https://example.test/lidar",
                        "published_at": "2026-05-27",
                        "title": "Nuevo dataset LiDAR y mapa de quebrada en Puerto Rico",
                        "summary": "Dataset GIS con DEM para análisis de hidrología.",
                        "location_text": "Puerto Rico",
                        "source_type": "dataset",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = main_with_args(
        [
            "--incoming",
            str(incoming),
            "--raw-output",
            str(raw_output),
            "--manifest",
            str(manifest),
            "--export-dir",
            str(export_dir),
            "--fail-on-validation-errors",
        ]
    )

    assert rc == 0
    assert raw_output.exists()
    assert manifest.exists()
    raw_rows = [json.loads(line) for line in raw_output.read_text(encoding="utf-8").splitlines()]
    assert len(raw_rows) == 2
    assert all(row["producer"] == "pr_news_raw_intake" for row in raw_rows)

    routing_summary = json.loads((export_dir / "routing_summary.json").read_text(encoding="utf-8"))
    assert routing_summary["zero_loss_pass"] is True
    assert routing_summary["raw_item_count"] == 2
    assert routing_summary["moneysweep_derivative_count"] == 1
    assert routing_summary["spiderweb_pr_derivative_count"] == 1

    verification = verify_exports(export_dir)
    assert verification["all_exports_exist"] is True
    saved_verification = json.loads(
        (export_dir / "export_verification.json").read_text(encoding="utf-8")
    )
    assert saved_verification["all_exports_exist"] is True
