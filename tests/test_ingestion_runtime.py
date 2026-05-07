"""Tests for Phase 2 standardized ingestion runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from contract_sweeper.runtime.ingestion_engine import IngestionEngine
from contract_sweeper.runtime.ingestion_interface import IngestionContext, IngestionSource, RetryPolicy
from contract_sweeper.runtime.manifest import IngestionManifest, write_manifest
from contract_sweeper.runtime.run_ingestion import build_execution_plan
from contract_sweeper.runtime.script_source import ScriptModuleSource
from contract_sweeper.runtime.source_registry import SourceDefinition, load_source_registry


@dataclass
class FlakySource(IngestionSource):
    attempts: int = 0

    def fetch(self, context: IngestionContext):
        self.attempts += 1
        if self.attempts < 2:
            raise RuntimeError("temporary failure")
        return [{"award_id": "A-1", "recipient_name": "Demo", "obligated_amount": "100"}]

    def normalize_raw(self, rows):
        return rows

    def validate_raw(self, rows):
        return {"ok": True, "missing_fields": [], "row_count": len(rows)}

    def write_manifest(self, context: IngestionContext, metadata: dict):
        manifest = IngestionManifest(
            source_id=context.source_id,
            run_id=context.run_id,
            status="OK" if metadata.get("ok") else "FAILED",
            started_at=metadata.get("started_at", IngestionManifest.now_iso()),
            ended_at=metadata.get("ended_at", IngestionManifest.now_iso()),
            row_count=int(metadata.get("row_count", 0)),
            retries=int(metadata.get("retries", 0)),
            field_completeness=dict(metadata.get("completeness", {})),
        )
        return write_manifest(manifest, (context.manifest_dir or context.output_dir) / "flaky.json")

    def log_completeness(self, context: IngestionContext, rows):
        return {"award_id": 1.0}


def test_registry_load_and_priority_plan():
    root = Path(__file__).resolve().parent.parent
    registry = load_source_registry(root / "configs/source_registry.yaml")

    assert registry.version == 1
    assert len(registry.sources) >= 12

    plan = build_execution_plan(registry)
    assert plan
    priorities = [item.priority for item in plan]
    assert priorities == sorted(priorities)


def test_ingestion_engine_retries_and_writes_manifest(tmp_path):
    context = IngestionContext(
        source_id="flaky",
        run_id="run-001",
        output_dir=tmp_path,
        project_root=tmp_path,
        manifest_dir=tmp_path / "manifests",
        retry_policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0.01, max_backoff_seconds=0.02),
    )
    source = FlakySource()
    engine = IngestionEngine()

    result = engine.run_source(source, context)

    assert result.status == "OK"
    assert result.row_count == 1
    assert result.retries == 1
    assert result.manifest_path.exists()


def test_script_module_source_adapter(tmp_path):
    module_dir = tmp_path / "fakepkg"
    module_dir.mkdir(parents=True)
    (module_dir / "__init__.py").write_text("", encoding="utf-8")
    (module_dir / "source_mod.py").write_text(
        "from pathlib import Path\n"
        "def run(root=None):\n"
        "    out = Path(root) / 'data' / 'staging' / 'processed'\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        "    p = out / 'fake.csv'\n"
        "    p.write_text('award_id,recipient_name,obligated_amount\\nA-1,Demo,100\\n', encoding='utf-8')\n"
        "    return {'master_path': str(p), 'master_rows': 1}\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(tmp_path))
    try:
        definition = SourceDefinition(
            source_id="fake_source",
            enabled=True,
            priority=1,
            module="fakepkg.source_mod",
            entrypoint="run",
            description="test module",
            output_paths=["data/staging/processed/fake.csv"],
            required_fields=["award_id", "recipient_name", "obligated_amount"],
            supports={
                "pagination": True,
                "retry_backoff": True,
                "resume": True,
                "cache": True,
                "time_window_splitting": True,
                "manifest": True,
                "completeness_logging": True,
            },
        )
        source = ScriptModuleSource(definition)
        context = IngestionContext(
            source_id="fake_source",
            run_id="run-xyz",
            output_dir=tmp_path,
            project_root=tmp_path,
            manifest_dir=tmp_path / "manifests",
        )

        rows = source.fetch(context)
        validation = source.validate_raw(rows)
        completeness = source.log_completeness(context, rows)
        manifest = source.write_manifest(context, {"ok": True, "row_count": len(rows), "completeness": completeness})

        assert len(rows) == 1
        assert validation["ok"] is True
        assert completeness["award_id"] == 1.0
        assert manifest.exists()
    finally:
        sys.path.remove(str(tmp_path))
