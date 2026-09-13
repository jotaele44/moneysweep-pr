from __future__ import annotations

import json

from server.backend.materialization_security import public_run_summary, write_offline_receipt


def test_offline_receipt_path_is_independent_of_source_metadata(tmp_path):
    receipt = write_offline_receipt(
        tmp_path,
        {
            "source_id": "../../outside",
            "raw_filename": "../operator-export.csv",
            "sha256": "a" * 64,
        },
    )

    receipt_path = tmp_path / "receipts" / "offline_ingest" / f"{receipt['receipt_id']}.json"
    assert receipt_path.is_file()
    assert receipt_path.parent == tmp_path / "receipts" / "offline_ingest"
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt


def test_public_run_summary_excludes_internal_paths_and_exception_details():
    public = public_run_summary(
        {
            "schema_version": "1.0.0",
            "selected_count": 1,
            "selected": ["test-source"],
            "registry_root": "/private/immutable-registry",
            "workspace_root": "/private/operator-workspace",
            "workspace_rebind": {"PROJECT_ROOT": "/private/operator-workspace"},
            "ran": [
                {
                    "source": "test-source",
                    "status": "ERROR",
                    "rows": None,
                    "error": "RuntimeError: credential=secret-value",
                }
            ],
            "error_count": 1,
        }
    )

    assert public == {
        "schema_version": "1.0.0",
        "selected_count": 1,
        "selected": ["test-source"],
        "error_count": 1,
        "ran": [
            {
                "source": "test-source",
                "status": "ERROR",
                "rows": None,
                "error_code": "ERROR",
            }
        ],
    }
