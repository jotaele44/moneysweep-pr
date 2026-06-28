"""Generic, deterministic detectors driven by federation.json canonical_outputs.

Detect broadly; the runner decides what (if anything) to correct. These never
mutate the repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import MaintenanceFinding


def _fid(repo: str, category: str, slug: str) -> str:
    return f"{repo}:{category}:{slug}"


def detect_missing_required_files(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    if not state["federation_json_present"]:
        findings.append(
            MaintenanceFinding(
                finding_id=_fid(repo, "manifest", "federation_json"),
                repo=repo,
                category="manifest",
                severity="critical",
                action="blocked",
                message="federation.json is missing",
                path="federation.json",
            )
        )
        return findings
    for key, present in state["canonical_outputs_present"].items():
        if key == "maintenance_report":
            continue  # self-referential: this is the report we are about to write
        if not present:
            rel = state["canonical_outputs"].get(key, key)
            findings.append(
                MaintenanceFinding(
                    finding_id=_fid(repo, "artifact_hygiene", key),
                    repo=repo,
                    category="artifact_hygiene",
                    severity="info",
                    action="none",
                    message=f"declared canonical output not present yet: {key}",
                    path=rel if isinstance(rel, str) else None,
                )
            )
    return findings


def detect_invalid_json(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    for key, rel in state["canonical_outputs"].items():
        if not isinstance(rel, str) or not rel.endswith(".json"):
            continue
        path = root / rel
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(
                MaintenanceFinding(
                    finding_id=_fid(repo, "schema", key),
                    repo=repo,
                    category="schema",
                    severity="error",
                    action="quarantined",
                    message=f"declared output {rel} is not valid JSON: {exc}",
                    path=rel,
                )
            )
    return findings


def _candidate_jsonl(root: Path, state: dict) -> list[Path]:
    paths: list[Path] = []
    outputs = state["canonical_outputs"]
    for rel in outputs.values():
        if isinstance(rel, str) and rel.endswith(".jsonl"):
            paths.append(root / rel)
    export_dir = outputs.get("canonical_export_dir")
    if isinstance(export_dir, str) and (root / export_dir).is_dir():
        paths.extend(sorted((root / export_dir).glob("*.jsonl")))
    return [p for p in paths if p.exists()]


def detect_exact_duplicate_jsonl(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    for path in _candidate_jsonl(root, state):
        seen: set[str] = set()
        dupes = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if line in seen:
                dupes += 1
            else:
                seen.add(line)
        if dupes:
            rel = str(path.relative_to(root))
            findings.append(
                MaintenanceFinding(
                    finding_id=_fid(repo, "duplicate", rel.replace("/", "_")),
                    repo=repo,
                    category="duplicate",
                    severity="warning",
                    action="none",
                    message=f"{dupes} exact duplicate row(s) in {rel}",
                    path=rel,
                    detail={"duplicate_rows": dupes},
                )
            )
    return findings
