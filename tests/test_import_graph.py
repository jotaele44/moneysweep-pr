"""Regression guard: no active code outside pipeline/ imports contract_sweeper.pipeline."""
import pytest
from pathlib import Path
from scripts.check_import_graph import scan, KNOWN_EXCEPTIONS

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_no_unexpected_pipeline_imports():
    violations = scan(ROOT)
    new = [v for v in violations if not v["known_exception"]]
    assert new == [], (
        f"{len(new)} unexpected import(s) of contract_sweeper.pipeline found:\n"
        + "\n".join(f"  {v['file']}:{v['line']}: {v['text']}" for v in new)
    )


@pytest.mark.unit
def test_known_exceptions_are_expected_files():
    assert "scripts/run_repo_quality_audit_r49z_b.py" in KNOWN_EXCEPTIONS
