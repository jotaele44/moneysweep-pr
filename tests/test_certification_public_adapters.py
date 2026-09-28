from pathlib import Path

import yaml

import tools.run_certification_public_adapters as adapters


def _root(tmp_path: Path) -> tuple[Path, Path, Path]:
    registry = tmp_path / "registry"
    workspace = tmp_path / "workspace"
    receipts = tmp_path / "receipts"
    (registry / "registries").mkdir(parents=True)
    (registry / "registries/source_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "test_v1",
                "sources": [
                    {
                        "source_id": "fixture",
                        "family": "test",
                        "required": True,
                        "authentication": "none",
                        "producer_script": "scripts/fixture.py",
                        "endpoint_url": "https://example.invalid/fixture",
                        "expected_outputs": [
                            "data/staging/processed/fixture.csv"
                        ],
                        "validation_threshold": {"min_rows": 1},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    output = workspace / "data/staging/processed/fixture.csv"
    output.parent.mkdir(parents=True)
    output.write_text("id\n1\n", encoding="utf-8")
    return registry, workspace, receipts


def test_failed_adapter_preserves_bytes_without_minting_fresh_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry, workspace, receipts = _root(tmp_path)

    def failed_runner(*, root: Path, force: bool):
        assert root == workspace.resolve()
        assert force is True
        return {"status": "error", "rows": 0}

    monkeypatch.setattr(
        adapters,
        "ADAPTERS",
        {
            "fixture": (
                "scripts/fixture.py",
                "https://example.invalid/fixture",
                failed_runner,
            )
        },
    )

    report = adapters.execute(
        registry_root=registry,
        workspace=workspace,
        receipts_dir=receipts,
        producer_sha="a" * 40,
    )
    result = report["sources"][0]

    assert result["state"] == "PUBLIC_ADAPTER_NO_OUTPUT" or result["state"] == (
        "PUBLIC_ADAPTER_OUTPUT_RECEIPTED_WITH_RUNNER_BLOCKER"
    )
    assert result["outputs"] == ["data/staging/processed/fixture.csv"]
    assert result["receipt_path"] is None
    assert result["receipt_error"] == (
        "execution_not_successful_no_acquisition_receipt"
    )
    assert not (receipts / "fixture.json").exists()


def test_successful_adapter_can_mint_receipt_for_current_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry, workspace, receipts = _root(tmp_path)

    def successful_runner(*, root: Path, force: bool):
        assert root == workspace.resolve()
        assert force is True
        return {"status": "complete", "rows": 1}

    monkeypatch.setattr(
        adapters,
        "ADAPTERS",
        {
            "fixture": (
                "scripts/fixture.py",
                "https://example.invalid/fixture",
                successful_runner,
            )
        },
    )

    report = adapters.execute(
        registry_root=registry,
        workspace=workspace,
        receipts_dir=receipts,
        producer_sha="b" * 40,
    )
    result = report["sources"][0]

    assert result["state"] == "PUBLIC_ADAPTER_RECEIPTED"
    assert result["receipt_path"] is not None
    assert result["receipt_error"] is None
    assert (receipts / "fixture.json").is_file()
