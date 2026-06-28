"""MoneySweep-specific maintenance checks (workbook Adapter Rules).

- check_source_registry_freshness: reports/materialization_readiness.json (the
  source of truth) exists and its counts reconcile.
- check_synthetic_leakage: synthetic rows (synthetic/is_synthetic/diagnostic_seed)
  must not appear in a PRODUCTION canonical export -> critical.
- check_vendor_duplicate_ids: exact-duplicate deterministic entity/source ids.

Read-only and audit-first. The synthetic-leakage check only fires for a
production-mode export; diagnostic/test exports legitimately carry synthetic rows.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from ..models import MaintenanceFinding

READINESS_PATH = "reports/materialization_readiness.json"
CANONICAL_EXPORT_DIR = "data/exports/canonical_v1_federation"


def _iter_jsonl(path: Path) -> Iterator[tuple[int, dict]]:
    if not path.exists():
        return
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield i, row


def check_source_registry_freshness(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    path = root / READINESS_PATH
    if not path.exists():
        return [
            MaintenanceFinding(
                finding_id=f"{repo}:source_staleness:readiness_missing",
                repo=repo,
                category="source_staleness",
                severity="error",
                action="quarantined",
                message=f"{READINESS_PATH} (source of truth) is missing",
                path=READINESS_PATH,
            )
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            MaintenanceFinding(
                finding_id=f"{repo}:source_staleness:readiness_invalid",
                repo=repo,
                category="source_staleness",
                severity="error",
                action="quarantined",
                message=f"materialization_readiness.json is not valid JSON: {exc}",
                path=READINESS_PATH,
            )
        ]
    ready, total = data.get("automatable_ready"), data.get("automatable_total")
    if isinstance(ready, int) and isinstance(total, int) and ready != total:
        findings.append(
            MaintenanceFinding(
                finding_id=f"{repo}:source_staleness:automatable_mismatch",
                repo=repo,
                category="source_staleness",
                severity="warning",
                action="none",
                message=f"automatable_ready ({ready}) != automatable_total ({total})",
                path=READINESS_PATH,
                detail={"automatable_ready": ready, "automatable_total": total},
            )
        )
    queued, queued_total = data.get("queued_excluded"), data.get("queued_excluded_total")
    if isinstance(queued, dict) and isinstance(queued_total, int):
        actual = sum(v for v in queued.values() if isinstance(v, int))
        if actual != queued_total:
            findings.append(
                MaintenanceFinding(
                    finding_id=f"{repo}:source_staleness:queued_excluded_mismatch",
                    repo=repo,
                    category="source_staleness",
                    severity="warning",
                    action="none",
                    message=f"queued_excluded_total ({queued_total}) != sum(queued_excluded) ({actual})",
                    path=READINESS_PATH,
                    detail={"queued_excluded_total": queued_total, "sum": actual},
                )
            )
    return findings


def _is_production(manifest: dict) -> bool:
    gate = str(manifest.get("gate") or manifest.get("mode") or "").upper()
    return gate.startswith("PRODUCTION") and "NON_PRODUCTION" not in gate


def check_synthetic_leakage(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    export = root / CANONICAL_EXPORT_DIR
    manifest_path = export / "manifest.json"
    if not manifest_path.exists():
        return findings
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return findings
    if not _is_production(manifest):
        return findings  # synthetic rows are legitimate outside production
    for stream in ("entities.jsonl", "sources.jsonl", "relationships.jsonl"):
        for i, row in _iter_jsonl(export / stream):
            if (
                row.get("synthetic") is True
                or row.get("is_synthetic") is True
                or "diagnostic_seed" in row
            ):
                findings.append(
                    MaintenanceFinding(
                        finding_id=f"{repo}:synthetic_leakage:{stream}_{i}",
                        repo=repo,
                        category="synthetic_leakage",
                        severity="critical",
                        action="blocked",
                        message=f"synthetic row in production export ({stream})",
                        path=f"{CANONICAL_EXPORT_DIR}/{stream}",
                        detail={"index": i},
                    )
                )
    return findings


def check_vendor_duplicate_ids(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    export = root / CANONICAL_EXPORT_DIR
    for stream, id_field in (("entities.jsonl", "entity_id"), ("sources.jsonl", "source_id")):
        seen: set = set()
        dupes: set = set()
        for _i, row in _iter_jsonl(export / stream):
            rid = row.get(id_field)
            if rid is None:
                continue
            if rid in seen:
                dupes.add(rid)
            else:
                seen.add(rid)
        if dupes:
            findings.append(
                MaintenanceFinding(
                    finding_id=f"{repo}:duplicate:{id_field}",
                    repo=repo,
                    category="duplicate",
                    severity="warning",
                    action="none",
                    message=f"{len(dupes)} duplicate {id_field}(s) in {stream}",
                    path=f"{CANONICAL_EXPORT_DIR}/{stream}",
                    detail={"duplicate_count": len(dupes)},
                )
            )
    return findings


CHECKS = (check_source_registry_freshness, check_synthetic_leakage, check_vendor_duplicate_ids)


def run_checks(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    for check in CHECKS:
        findings.extend(check(repo, root, state))
    return findings
