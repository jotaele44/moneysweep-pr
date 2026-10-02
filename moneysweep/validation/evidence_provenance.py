"""Evidence provenance certification for Canonical v1.

Source taxonomy is not source identity. A row does not become T1 merely because
``source_type`` says ``registry``/``filing``/``court_docket``. Certification
requires an explicit authoritative binding in
``data/manifests/evidence_source_bindings.json``.

The binding registry is deliberately separate from evidence rows so RAW source
strings remain immutable and provenance adjudication can evolve without
silently rewriting observations.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = Path("data/canonical_v1/evidence.csv")
BINDINGS_PATH = Path("data/manifests/evidence_source_bindings.json")
AUTHORITATIVE_STATUS = "authoritative"


@dataclass
class ProvenanceReport:
    row_count: int = 0
    tier_counts: dict[str, int] = field(default_factory=dict)
    authoritative_binding_count: int = 0
    unbound_t1_count: int = 0
    t1_source_surface_count: int = 0
    t1_state_counts: dict[str, int] = field(default_factory=dict)
    source_surfaces: list[dict[str, Any]] = field(default_factory=list)
    arithmetic_closed: bool = False
    issues: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.unbound_t1_count == 0 and self.arithmetic_closed

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "row_count": self.row_count,
            "tier_counts": self.tier_counts,
            "authoritative_binding_count": self.authoritative_binding_count,
            "unbound_t1_count": self.unbound_t1_count,
            "t1_source_surface_count": self.t1_source_surface_count,
            "t1_state_counts": self.t1_state_counts,
            "source_surfaces": self.source_surfaces,
            "arithmetic_closed": self.arithmetic_closed,
            "issues": self.issues,
        }


def load_bindings(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return binding_key -> binding record. Missing registry means no bindings."""
    root = root or REPO_ROOT
    path = root / BINDINGS_PATH
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("bindings", []) if isinstance(payload, dict) else []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("binding_key") or "").strip()
        if key:
            out[key] = row
    return out


def binding_key_for(row: dict[str, str]) -> str:
    """Stable source-manifestation key used for authority adjudication."""
    return (row.get("source_path_or_url") or "").strip()


def _authoritative_identity_is_complete(key: str, binding: dict[str, Any]) -> bool:
    """Require authority identity and, for local manifestations, byte identity.

    A local transformed file cannot become T1 because it merely names an
    authority. It must be frozen by SHA256 *and* bound to a stable authority ID
    or authority URL. Remote authoritative sources require explicit stable
    authority identity but cannot satisfy the gate by URL-shape alone.
    """
    if binding.get("status") != AUTHORITATIVE_STATUS:
        return False
    stable_authority = bool(binding.get("stable_id") or binding.get("authority_url"))
    local = bool(key) and not key.startswith(("http://", "https://"))
    if local:
        return stable_authority and bool(binding.get("sha256"))
    return stable_authority


def audit_evidence(root: Path | None = None) -> ProvenanceReport:
    root = root or REPO_ROOT
    bindings = load_bindings(root)
    report = ProvenanceReport()
    surface_rows: dict[str, list[dict[str, Any]]] = {}

    with (root / EVIDENCE_PATH).open(newline="", encoding="utf-8") as fh:
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            report.row_count += 1
            tier = (row.get("evidence_tier") or "").strip()
            report.tier_counts[tier] = report.tier_counts.get(tier, 0) + 1
            if tier != "T1":
                continue

            key = binding_key_for(row)
            surface_rows.setdefault(key, []).append({"line": line_no, "row": row})
            binding = bindings.get(key, {})
            state = str(binding.get("status") or "unregistered")
            complete = _authoritative_identity_is_complete(key, binding)
            if complete:
                report.authoritative_binding_count += 1
                row_state = "authoritative"
            else:
                report.unbound_t1_count += 1
                row_state = state if state in {"noncanonical", "unresolved"} else "unregistered"
                report.issues.append(
                    {
                        "classification": "SOURCE_TAXONOMY_NOT_IDENTITY",
                        "line": line_no,
                        "evidence_id": row.get("evidence_id"),
                        "source_type": row.get("source_type"),
                        "source_name": row.get("source_name"),
                        "source_path_or_url": key,
                        "evidence_tier": tier,
                        "state": row_state.upper(),
                        "reason": (
                            "T1 requires explicit authoritative identity; local manifestations "
                            "also require frozen SHA256 byte identity"
                        ),
                    }
                )
            report.t1_state_counts[row_state] = report.t1_state_counts.get(row_state, 0) + 1

    report.t1_source_surface_count = len(surface_rows)
    for key in sorted(surface_rows):
        binding = bindings.get(key, {})
        complete = _authoritative_identity_is_complete(key, binding)
        status = "authoritative" if complete else str(binding.get("status") or "unregistered")
        report.source_surfaces.append(
            {
                "binding_key": key,
                "t1_row_count": len(surface_rows[key]),
                "status": status,
                "source_class": binding.get("source_class"),
                "stable_id": binding.get("stable_id"),
                "authority_url": binding.get("authority_url"),
                "sha256": binding.get("sha256"),
                "reason": binding.get("reason"),
            }
        )

    t1_rows = report.tier_counts.get("T1", 0)
    classified_rows = sum(report.t1_state_counts.values())
    report.arithmetic_closed = classified_rows == t1_rows
    if not report.arithmetic_closed:
        report.issues.append(
            {
                "classification": "COUNT",
                "state": "FAIL",
                "reason": f"T1 arithmetic mismatch: classified={classified_rows} total={t1_rows}",
            }
        )
    return report
