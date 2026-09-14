from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import canonical_json, sha256_bytes, sha256_file
    from tools.verify_source_equivalence import verify
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import canonical_json, sha256_bytes, sha256_file  # type: ignore[no-redef]
    from verify_source_equivalence import verify  # type: ignore[no-redef]

REPORT_SCHEMA_VERSION = "moneysweep.source_equivalence_claim_set/v1"
DEFAULT_CLAIMS_DIR = Path("registries/source_equivalence_claims")
DEFAULT_OUTPUT = Path("reports/source_equivalence_verification.json")


def _load_claim(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("claim must contain a JSON object")
    return payload


def build_report(*, root: Path, claims_dir: Path = DEFAULT_CLAIMS_DIR) -> dict[str, Any]:
    root = root.resolve()
    directory = claims_dir if claims_dir.is_absolute() else root / claims_dir
    claim_paths = sorted(directory.glob("*.json")) if directory.exists() else []

    claims: list[dict[str, Any]] = []
    claim_errors: list[str] = []
    seen_claim_identity: set[tuple[str, str]] = set()

    for path in claim_paths:
        relative = path.relative_to(root).as_posix()
        try:
            payload = _load_claim(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            claim_errors.append(f"{relative}:unreadable:{type(exc).__name__}")
            continue

        verification = verify(root=root, claim=payload)
        candidate = verification.get("candidate_source")
        candidate_name = (
            str(candidate.get("name", "")).strip() if isinstance(candidate, dict) else ""
        )
        identity = (str(verification.get("source_id", "")).strip(), candidate_name)
        if identity in seen_claim_identity:
            claim_errors.append(f"{relative}:duplicate_claim_identity:{identity[0]}:{identity[1]}")
        seen_claim_identity.add(identity)

        contract_valid = not verification.get("errors") and not verification.get("evidence_blockers")
        if not contract_valid:
            claim_errors.append(f"{relative}:claim_evidence_invalid")

        claims.append(
            {
                "claim_path": relative,
                "claim_sha256": sha256_file(path),
                "source_id": verification.get("source_id"),
                "candidate_name": candidate_name,
                "decision": verification.get("decision"),
                "certified_equivalent": verification.get("certified_equivalent") is True,
                "claim_evidence_valid": contract_valid,
                "verified_evidence_count": verification.get("verified_evidence_count", 0),
                "evidence_count": verification.get("evidence_count", 0),
                "errors": verification.get("errors", []),
                "blockers": verification.get("blockers", []),
                "evidence_blockers": verification.get("evidence_blockers", []),
                "registered_source_definition_sha256": verification.get(
                    "registered_source_definition_sha256"
                ),
            }
        )

    claims.sort(key=lambda item: (str(item["source_id"]), item["claim_path"]))
    decision_counts: dict[str, int] = {}
    for claim in claims:
        decision = str(claim.get("decision") or "UNKNOWN")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "claims_dir": claims_dir.as_posix(),
        "claim_count": len(claims),
        "claim_set_valid": not claim_errors,
        "claim_errors": sorted(set(claim_errors)),
        "certified_equivalent_count": sum(
            claim["certified_equivalent"] is True for claim in claims
        ),
        "non_certifying_claim_count": sum(
            claim["certified_equivalent"] is not True for claim in claims
        ),
        "decision_counts": dict(sorted(decision_counts.items())),
        "claims": claims,
        "policy": {
            "claim_contract_must_validate": True,
            "evidence_bytes_must_verify": True,
            "non_equivalent_claim_is_not_claim_set_failure": True,
            "substitution_requires_certified_equivalent": True,
            "silent_substitution_allowed": False,
        },
    }
    report["claim_set_sha256"] = sha256_bytes(canonical_json(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify every registered source-equivalence claim without granting implicit substitution."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--claims-dir", type=Path, default=DEFAULT_CLAIMS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    root = args.root.resolve()
    report = build_report(root=root, claims_dir=args.claims_dir)
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["claim_set_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
