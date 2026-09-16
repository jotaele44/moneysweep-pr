from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.certification_truth_guards import EvidenceError, aware_datetime
from tools.derive_certification_truth import derive

SCHEMA_VERSION = "moneysweep.certification_scope_bound/v1"


def _git_head(root: Path) -> str | None:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def derive_scope_bound(
    *,
    root: Path,
    evidence_root: Path,
    receipts_dir: Path | None,
    execution_receipts_dir: Path | None,
    scope_dir: Path,
    as_of: datetime,
    operator_corpus_id: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    evidence_root = evidence_root.resolve()
    root_sha = _git_head(root)
    if root_sha is None:
        raise EvidenceError("scope_repository_head_unavailable")
    evidence_sha = _git_head(evidence_root)
    if evidence_sha is None:
        raise EvidenceError("evidence_repository_head_unavailable")

    result = derive(
        root=root,
        evidence_root=evidence_root,
        receipts_dir=receipts_dir,
        execution_receipts_dir=execution_receipts_dir,
        scope_dir=scope_dir,
        as_of=as_of,
        operator_corpus_id=operator_corpus_id,
    )

    manifest_path = Path(result["scope_manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = manifest.get("scope_identity")
    if not isinstance(identity, dict):
        raise EvidenceError("scope_identity_missing")
    if identity.get("scope_repository_sha") != root_sha:
        raise EvidenceError("scope_repository_sha_mismatch")

    bound = dict(identity)
    bound.update(
        {
            "scope_repository_sha": root_sha,
            "evidence_repository_sha": evidence_sha,
            "evidence_repository_same_as_scope": evidence_root == root,
        }
    )
    manifest["scope_identity"] = bound
    manifest["scope_id"] = _digest(bound)
    manifest["scope_binding"] = {
        "schema_version": SCHEMA_VERSION,
        "scope_repository_sha": root_sha,
        "evidence_repository_sha": evidence_sha,
        "evidence_repository_same_as_scope": evidence_root == root,
        "path_strings_are_identity": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result["scope_manifest"] = manifest
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive certification truth with explicit evidence-repository identity binding."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--receipts-dir", type=Path)
    parser.add_argument("--execution-receipts-dir", type=Path)
    parser.add_argument("--scope-dir", type=Path, required=True)
    parser.add_argument("--operator-corpus-id")
    parser.add_argument("--as-of")
    args = parser.parse_args()

    root = args.root.resolve()
    evidence_root = (args.evidence_root or root).resolve()
    as_of = aware_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of is None:
        raise SystemExit("--as-of must be an ISO-8601 timestamp")
    result = derive_scope_bound(
        root=root,
        evidence_root=evidence_root,
        receipts_dir=args.receipts_dir.resolve() if args.receipts_dir else None,
        execution_receipts_dir=(
            args.execution_receipts_dir.resolve() if args.execution_receipts_dir else None
        ),
        scope_dir=args.scope_dir.resolve(),
        as_of=as_of,
        operator_corpus_id=args.operator_corpus_id,
    )
    print(
        json.dumps(
            {
                "scope_id": result["scope_manifest"]["scope_id"],
                "scope_repository_sha": result["scope_manifest"]["scope_binding"][
                    "scope_repository_sha"
                ],
                "evidence_repository_sha": result["scope_manifest"]["scope_binding"][
                    "evidence_repository_sha"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
