import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_route_pr_intake_cli_exports_derivative_csvs(tmp_path):
    out_dir = tmp_path / "router_exports"
    cmd = [
        sys.executable,
        str(_ROOT / "scripts" / "route_pr_intake.py"),
        "--input",
        str(_ROOT / "tests" / "fixtures" / "pr_intake_router_sample.jsonl"),
        "--out-dir",
        str(out_dir),
    ]

    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    summary = json.loads(completed.stdout)

    assert summary["zero_loss_pass"] is True
    assert summary["raw_item_count"] == 4
    assert summary["route_result_count"] == 4
    assert summary["moneysweep_derivative_count"] >= 2
    assert summary["spiderweb_pr_derivative_count"] >= 2
    assert summary["review_queue_count"] >= 1

    assert (out_dir / "route_results.jsonl").exists()
    assert (out_dir / "moneysweep_derivatives.csv").exists()
    assert (out_dir / "spiderweb_pr_derivatives.csv").exists()
    assert (out_dir / "manual_review_queue.csv").exists()
    assert (out_dir / "routing_summary.json").exists()

    saved_summary = json.loads((out_dir / "routing_summary.json").read_text(encoding="utf-8"))
    assert saved_summary == summary

    route_lines = (out_dir / "route_results.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(route_lines) == 4


def test_route_pr_intake_cli_fails_on_validation_errors_when_requested(tmp_path):
    input_path = tmp_path / "bad_spatial.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "source_item_id": "RAW-BAD-001",
                "source_name": "NOAA",
                "source_url": "https://example.test/weather",
                "published_at": "2026-05-27",
                "discovered_at": "2026-05-27T12:00:00Z",
                "title": "NOAA publica dataset de weather monitoring",
                "summary": "Dataset ambiental sin ubicación.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "router_exports"
    cmd = [
        sys.executable,
        str(_ROOT / "scripts" / "route_pr_intake.py"),
        "--input",
        str(input_path),
        "--out-dir",
        str(out_dir),
        "--fail-on-validation-errors",
    ]

    completed = subprocess.run(cmd, capture_output=True, text=True)

    assert completed.returncode == 2
    assert (out_dir / "routing_summary.json").exists()
    summary = json.loads((out_dir / "routing_summary.json").read_text(encoding="utf-8"))
    assert summary["zero_loss_pass"] is True
    assert summary["validation_error_count"] == 1
