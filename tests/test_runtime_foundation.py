"""Tests for Phase 1 runtime foundation modules."""

from __future__ import annotations

import json
from pathlib import Path

from contract_sweeper.runtime.cache import FileCache
from contract_sweeper.runtime.config import load_runtime_config
from contract_sweeper.runtime.ingestion_interface import IngestionContext, IngestionSource
from contract_sweeper.runtime.logging import configure_logging
from contract_sweeper.runtime.manifest import IngestionManifest, write_manifest
from contract_sweeper.runtime.schema_registry import load_schema_registry
from contract_sweeper.runtime.source_registry import load_source_registry
from contract_sweeper.runtime.validation import validate_required_fields


class DummySource(IngestionSource):
    def fetch(self, context: IngestionContext):
        return [{"record_id": "1"}]

    def normalize_raw(self, rows):
        return rows

    def validate_raw(self, rows):
        return {"ok": True, "rows": len(rows)}

    def write_manifest(self, context: IngestionContext, metadata):
        path = context.output_dir / "dummy_manifest.json"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        return path

    def log_completeness(self, context: IngestionContext, rows):
        return {"record_id": 1.0 if rows else 0.0}


def test_runtime_modules_importable():
    logger = configure_logging("INFO")
    assert logger.name == "contract_sweeper"


def test_load_runtime_config_defaults(tmp_path):
    cfg = load_runtime_config(project_root=tmp_path)
    assert cfg.project_root == tmp_path.resolve()
    assert cfg.configs_dir == (tmp_path / "configs").resolve()
    assert cfg.cache_dir == (tmp_path / "data/cache").resolve()


def test_load_runtime_config_env_file(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "CONTRACT_SWEEPER_ENV=ci\nCONTRACT_SWEEPER_LOG_LEVEL=debug\n",
        encoding="utf-8",
    )
    cfg = load_runtime_config(project_root=tmp_path)
    assert cfg.environment == "ci"
    assert cfg.log_level == "DEBUG"


def test_load_repo_registries():
    root = Path(__file__).resolve().parent.parent
    source_registry = load_source_registry(root / "configs/source_registry.yaml")
    schema_registry = load_schema_registry(root / "configs/schema_registry.yaml")

    assert source_registry.version == 1
    assert isinstance(source_registry.sources, list)
    assert schema_registry.version == 1
    assert len(schema_registry.datasets) >= 1


def test_manifest_writer(tmp_path):
    manifest = IngestionManifest(
        source_id="demo",
        run_id="run-001",
        status="OK",
        started_at=IngestionManifest.now_iso(),
        ended_at=IngestionManifest.now_iso(),
        row_count=10,
    )
    target = tmp_path / "manifests" / "demo.json"
    out = write_manifest(manifest, target)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source_id"] == "demo"
    assert payload["row_count"] == 10


def test_file_cache_roundtrip(tmp_path):
    cache = FileCache(tmp_path, namespace="runtime")
    cache.set("alpha", {"value": 123})
    entry = cache.get("alpha")
    assert entry is not None
    assert entry.payload["value"] == 123
    assert cache.get_if_fresh("alpha", ttl_seconds=3600) is not None


def test_validate_required_fields():
    rows = [
        {"entity_id": "A", "award_id": "X"},
        {"entity_id": "B", "award_id": ""},
    ]
    result = validate_required_fields(rows, ["entity_id", "award_id", "agency"])
    assert result.ok is False
    assert "agency" in result.missing_fields
    assert result.row_count == 2
    assert result.completeness["entity_id"] == 1.0


def test_ingestion_interface_contract(tmp_path):
    source = DummySource()
    context = IngestionContext(source_id="demo", run_id="run-001", output_dir=tmp_path)

    raw_rows = source.fetch(context)
    normalized = source.normalize_raw(raw_rows)
    checks = source.validate_raw(raw_rows)
    metrics = source.log_completeness(context, raw_rows)
    manifest_path = source.write_manifest(context, checks)

    assert len(normalized) == 1
    assert checks["ok"] is True
    assert metrics["record_id"] == 1.0
    assert manifest_path.exists()
