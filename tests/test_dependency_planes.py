from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_dependency_planes", ROOT / "scripts" / "validate_dependency_planes.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

RUNTIME = """pandas>=3
requests>=2
prii-maintenance @ git+https://example.test/hub.git@abc#subdirectory=maintenance
"""
RUNTIME_LOCK = """certifi==1
pandas==3
requests==2
prii-maintenance @ git+https://example.test/hub.git@abc#subdirectory=maintenance
"""
DEV = """-r requirements.txt
ruff==1
mypy==1
pytest==9.1.1
pytest-cov==7.1.0
"""
COMMANDS = {
    "setup": "python -m pip install -r requirements-dev.txt",
    "runtime_setup": "python -m pip install -r requirements.txt",
    "test_suite": "python -m pytest -q",
}


def _write(
    root: Path,
    *,
    runtime_input=RUNTIME,
    runtime_requirements=RUNTIME,
    runtime_lock=RUNTIME_LOCK,
    dev=DEV,
    commands=COMMANDS,
):
    (root / "requirements.in").write_text(runtime_input, encoding="utf-8")
    (root / "requirements.txt").write_text(runtime_requirements, encoding="utf-8")
    (root / "requirements.lock").write_text(runtime_lock, encoding="utf-8")
    (root / "requirements-dev.txt").write_text(dev, encoding="utf-8")
    (root / "federation.json").write_text(
        json.dumps({"hub_callable_commands": commands}), encoding="utf-8"
    )


def test_repository_dependency_planes_pass() -> None:
    summary = validator.validate(ROOT)
    assert summary["status"] == "PASS"
    assert summary["runtime_manifests_byte_identical"] is True
    assert summary["test_packages_in_runtime"] == 0
    assert summary["hub_runtime_profile_bound"] is True


def test_runtime_manifest_drift_fails(tmp_path: Path) -> None:
    _write(tmp_path, runtime_requirements=RUNTIME + "lxml\n")
    with pytest.raises(validator.DependencyPlaneError, match="byte-identical"):
        validator.validate(tmp_path)


def test_runtime_test_dependency_fails(tmp_path: Path) -> None:
    contaminated = RUNTIME + "pytest==9.1.1\n"
    _write(
        tmp_path,
        runtime_input=contaminated,
        runtime_requirements=contaminated,
        runtime_lock=RUNTIME_LOCK + "pytest==9.1.1\n",
    )
    with pytest.raises(validator.DependencyPlaneError, match="leaked into runtime"):
        validator.validate(tmp_path)


def test_runtime_direct_requirement_must_be_locked(tmp_path: Path) -> None:
    _write(tmp_path, runtime_lock="pandas==3\nrequests==2\n")
    with pytest.raises(validator.DependencyPlaneError, match="missing from runtime lock"):
        validator.validate(tmp_path)


def test_development_manifest_must_include_runtime(tmp_path: Path) -> None:
    _write(tmp_path, dev="pytest==9.1.1\npytest-cov==7.1.0\n")
    with pytest.raises(validator.DependencyPlaneError, match="must include"):
        validator.validate(tmp_path)


def test_hub_runtime_profile_cannot_install_dev_manifest(tmp_path: Path) -> None:
    commands = dict(COMMANDS)
    commands["runtime_setup"] = "python -m pip install -r requirements-dev.txt"
    _write(tmp_path, commands=commands)
    with pytest.raises(validator.DependencyPlaneError, match="only requirements.txt"):
        validator.validate(tmp_path)


def test_hub_setup_must_prepare_tests(tmp_path: Path) -> None:
    commands = dict(COMMANDS)
    commands["setup"] = "python -m pip install -r requirements.txt"
    _write(tmp_path, commands=commands)
    with pytest.raises(validator.DependencyPlaneError, match="audit/test profile"):
        validator.validate(tmp_path)
