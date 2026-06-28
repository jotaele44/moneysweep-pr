"""Narrow, deterministic corrections. Only invoked in explicit safe-correct mode.

Never runs in audit mode. The only correction is exact-duplicate JSONL row
removal; ambiguous/interpretive issues are quarantined, never auto-merged.
"""

from __future__ import annotations

from pathlib import Path

from .models import MaintenanceFinding


def remove_exact_duplicate_jsonl_rows(path: Path) -> int:
    """Drop exact-duplicate lines in place; return the number removed."""
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    kept: list[str] = []
    removed = 0
    for line in lines:
        if line.strip() and line in seen:
            removed += 1
            continue
        if line.strip():
            seen.add(line)
        kept.append(line)
    if removed:
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed


def plan_safe_corrections(findings: list[MaintenanceFinding]) -> list[MaintenanceFinding]:
    """Return only the findings that are safe to auto-correct (exact duplicates)."""
    return [f for f in findings if f.category == "duplicate" and f.severity == "warning" and f.path]
