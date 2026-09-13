#!/usr/bin/env python3
"""Build a fail-closed, atomic MoneySweep database certification bundle.

Independent vectors:
  A. canonical_v1 denominator/schema/PK/FK/provenance structure
  B. evidence authority bindings + federation package byte/count identity
  C. Case Manager SQLite runtime bytes/integrity/FKs/audit/evidence references

A CERTIFIED release requires all three vectors to PASS. Missing runtime SQLite
bytes are BLOCKED, never silently converted into a pass.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from moneysweep.validation.canonical_v1_schema import TABLES, validate_all  # noqa: E402
from moneysweep.validation.case_manager_sqlite import certify_sqlite  # noqa: E402
from moneysweep.validation.evidence_provenance import audit_evidence  # noqa: E402
from moneysweep.validation.federation_package import (  # noqa: E402
    certify_federation_package,
)

RELEASES_DIR = Path("data/manifests/database_releases")
DEFAULT_SQLITE = Path("data/case_manager.sqlite3")
DEFAULT_EVIDENCE = Path("data/canonical_v1/evidence.csv")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _canonical_files(root: Path, counts: dict[str, int]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for table, (schema_name, csv_name, pk) in TABLES.items():
        csv_path = root / "data/canonical_v1" / csv_name
        schema_path = root / "schemas/canonical_v1" / schema_name
        with csv_path.open(newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh), [])
        files.append(
            {
                "table": table,
                "csv": f"data/canonical_v1/{csv_name}",
                "schema": f"schemas/canonical_v1/{schema_name}",
                "primary_key": pk,
                "row_count": counts.get(table, 0),
                "column_count": len(header),
                "columns": header,
                "size_bytes": csv_path.stat().st_size,
                "sha256": _sha256(csv_path),
                "schema_sha256": _sha256(schema_path),
            }
        )
    return files


def _release_digest(
    git_head: str | None,
    canonical_files: list[dict[str, Any]],
    federation: dict[str, Any],
    sqlite_report: dict[str, Any],
) -> str:
    payload = {
        "git_head": git_head,
        "canonical": [[row["csv"], row["sha256"], row["schema_sha256"]] for row in canonical_files],
        "federation_package_id": federation.get("package_id"),
        "federation_files": [
            [row.get("filename"), row.get("actual_sha256")] for row in federation.get("files", [])
        ],
        "sqlite_sha256": sqlite_report.get("sha256"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_canonical_csv(path: Path, files: list[dict[str, Any]]) -> None:
    fields = [
        "table",
        "csv",
        "schema",
        "primary_key",
        "row_count",
        "column_count",
        "size_bytes",
        "sha256",
        "schema_sha256",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(files)


def _fsync_tree(directory: Path) -> None:
    for path in directory.rglob("*"):
        if path.is_file():
            with path.open("rb") as fh:
                os.fsync(fh.fileno())
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def build_report(root: Path, sqlite_path: Path) -> dict[str, Any]:
    canonical = validate_all(root)
    evidence = audit_evidence(root)
    federation = certify_federation_package(root).to_dict()
    sqlite_report = certify_sqlite(sqlite_path, root / DEFAULT_EVIDENCE).to_dict()
    canonical_files = _canonical_files(root, canonical.counts)
    git_head = _git_head(root)

    vector_a = "PASS" if canonical.ok else "FAIL"
    vector_b = "PASS" if evidence.ok and federation["ok"] else "FAIL"
    vector_c = sqlite_report["status"]
    status = (
        "CERTIFIED"
        if (vector_a, vector_b, vector_c) == ("PASS", "PASS", "PASS")
        else (
            "BLOCKED"
            if vector_c == "BLOCKED" and vector_a == "PASS" and vector_b == "PASS"
            else "FAIL"
        )
    )
    digest = _release_digest(git_head, canonical_files, federation, sqlite_report)
    release_id = f"dbrel_{digest[:24]}"
    return {
        "release_id": release_id,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "scope": {
            "canonical_model": "canonical_v1",
            "canonical_table_count": len(TABLES),
            "federation_package": "data/exports/canonical_v1_federation",
            "case_manager_sqlite": str(sqlite_path.relative_to(root))
            if sqlite_path.is_relative_to(root)
            else str(sqlite_path),
        },
        "vectors": {
            "A_CANONICAL_DATABASE": vector_a,
            "B_PROVENANCE_AND_FEDERATION": vector_b,
            "C_SQLITE_RUNTIME": vector_c,
        },
        "canonical_validation": canonical.to_dict(),
        "canonical_files": canonical_files,
        "evidence_provenance": evidence.to_dict(),
        "federation": federation,
        "sqlite": sqlite_report,
        "zero_unresolved_residue": status == "CERTIFIED",
    }


def write_atomic_release(root: Path, report: dict[str, Any]) -> Path:
    releases = root / RELEASES_DIR
    releases.mkdir(parents=True, exist_ok=True)
    final = releases / report["release_id"]
    if final.exists():
        existing = json.loads((final / "release.json").read_text(encoding="utf-8"))
        if existing.get("release_id") != report["release_id"]:
            raise RuntimeError("release-id collision")
        return final

    tmp = Path(tempfile.mkdtemp(prefix=".tmp-dbrel-", dir=releases))
    try:
        _write_json(tmp / "release.json", report)
        _write_json(tmp / "canonical_tables.json", report["canonical_files"])
        _write_canonical_csv(tmp / "canonical_tables.csv", report["canonical_files"])
        _write_json(tmp / "evidence_provenance.json", report["evidence_provenance"])
        _write_json(tmp / "federation.json", report["federation"])
        _write_json(tmp / "sqlite.json", report["sqlite"])
        checksums = []
        for path in sorted(p for p in tmp.iterdir() if p.is_file()):
            checksums.append(f"{_sha256(path)}  {path.name}")
        (tmp / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
        _fsync_tree(tmp)
        os.replace(tmp, final)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--sqlite", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="write atomic release bundle")
    parser.add_argument(
        "--allow-blocked-sqlite",
        action="store_true",
        help="return 0 when only the unmaterialized runtime SQLite vector is BLOCKED",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    sqlite_path = (args.sqlite or (root / DEFAULT_SQLITE)).resolve()
    report = build_report(root, sqlite_path)
    if args.write:
        report["release_path"] = str(write_atomic_release(root, report).relative_to(root))
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] == "CERTIFIED":
        return 0
    if report["status"] == "BLOCKED" and args.allow_blocked_sqlite:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
