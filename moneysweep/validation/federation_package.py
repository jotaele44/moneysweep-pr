"""Certify the committed canonical_v1 federation package against its manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = Path("data/exports/canonical_v1_federation")


@dataclass
class FederationReport:
    status: str = "PASS"
    package_id: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "PASS" and not self.issues

    def add(self, message: str) -> None:
        self.issues.append(message)
        self.status = "FAIL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "package_id": self.package_id,
            "files": self.files,
            "issues": self.issues,
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonl_count(path: Path) -> tuple[int, list[str]]:
    count = 0
    issues: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                issues.append(f"{path.name}:{line_no}: blank JSONL record")
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append(f"{path.name}:{line_no}: invalid JSON: {exc}")
                continue
            if not isinstance(value, dict):
                issues.append(f"{path.name}:{line_no}: JSONL record is not an object")
            count += 1
    return count, issues


def certify_federation_package(
    root: Path | None = None, package: Path = DEFAULT_PACKAGE
) -> FederationReport:
    root = root or REPO_ROOT
    package_dir = root / package
    report = FederationReport()
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        report.status = "BLOCKED"
        report.issues.append("federation manifest missing")
        return report
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report.package_id = manifest.get("package_id")
    declared = manifest.get("files") or []
    declared_names = [str(item.get("filename") or "") for item in declared]
    if len(declared_names) != len(set(declared_names)):
        report.add("duplicate filenames in federation manifest")

    actual_jsonl = sorted(p.name for p in package_dir.glob("*.jsonl") if p.is_file())
    if sorted(declared_names) != actual_jsonl:
        report.add(
            f"federation denominator mismatch declared={sorted(declared_names)} actual={actual_jsonl}"
        )

    for item in declared:
        name = str(item.get("filename") or "")
        path = package_dir / name
        result: dict[str, Any] = {
            "filename": name,
            "stream": item.get("stream"),
            "schema_id": item.get("schema_id"),
            "declared_record_count": item.get("record_count"),
            "declared_sha256": item.get("sha256"),
        }
        if not path.exists():
            report.add(f"declared federation file missing: {name}")
            result["status"] = "MISSING"
            report.files.append(result)
            continue
        actual_sha = _sha256(path)
        actual_count, json_issues = _jsonl_count(path)
        result.update(
            {
                "actual_sha256": actual_sha,
                "actual_record_count": actual_count,
                "status": "PASS",
            }
        )
        if actual_sha != item.get("sha256"):
            report.add(f"{name}: SHA256 mismatch")
            result["status"] = "FAIL"
        if actual_count != item.get("record_count"):
            report.add(
                f"{name}: record_count mismatch declared={item.get('record_count')} actual={actual_count}"
            )
            result["status"] = "FAIL"
        for issue in json_issues:
            report.add(issue)
            result["status"] = "FAIL"
        report.files.append(result)
    return report
