"""Source-level candidate coverage of the 25 domains.

Projects the registered source denominator onto the ontology. It reports which
domains have any registered source at all; it certifies nothing about rows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ._common import FinancialIntelligenceError
from .ontology import REPO_ROOT, load_ontology

BINDINGS_PATH = REPO_ROOT / "registries" / "financial_intelligence_source_bindings_v1.json"
OUT_JSON = REPO_ROOT / "reports" / "financial_intelligence_domain_coverage_v1.json"
OUT_MD = REPO_ROOT / "reports" / "financial_intelligence_domain_coverage_v1.md"
NOT_CONSIDERED = "not_considered"
MATERIALIZING = frozenset({"wired_materializing", "wired_offline_ready"})


def load_bindings(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or BINDINGS_PATH).read_text(encoding="utf-8"))


def read_audit_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_coverage(
    ontology: dict[str, Any], bindings: dict[str, Any], audit_rows: list[dict[str, str]]
) -> dict[str, Any]:
    """Conserve the source denominator across bound, unbound and unclassified."""
    domain_ids = [domain["id"] for domain in ontology["domains"]]
    status = {row["source_id"]: row["audit_status"] for row in audit_rows}
    if len(status) != len(audit_rows):
        raise FinancialIntelligenceError("duplicate source in the audit denominator")
    bound: dict[str, list[str]] = bindings["bindings"]
    unbound: dict[str, str] = bindings["unbound"]

    if set(bound) & set(unbound):
        raise FinancialIntelligenceError("a source is both bound and unbound")
    phantom = sorted((set(bound) | set(unbound)) - set(status))
    if phantom:
        raise FinancialIntelligenceError(f"binding names an unregistered source: {phantom}")
    for source_id, domains in bound.items():
        if not domains or set(domains) - set(domain_ids):
            raise FinancialIntelligenceError(f"{source_id}: empty or unknown domain binding")

    per_domain: dict[str, Any] = {}
    for domain in ontology["domains"]:
        sources = sorted(s for s, ids in bound.items() if domain["id"] in ids)
        tally = Counter(status[s] for s in sources)
        registered = [s for s in sources if status[s] != NOT_CONSIDERED]
        per_domain[domain["id"]] = {
            "name": domain["name"],
            "priority": domain["priority"],
            "registered_sources": len(registered),
            "materializing_sources": sum(tally[bucket] for bucket in MATERIALIZING),
            "not_considered_candidates": tally[NOT_CONSIDERED],
            "by_audit_status": dict(sorted(tally.items())),
            "sources": sources,
        }

    unclassified = sorted(set(status) - set(bound) - set(unbound))
    registry_sources = [s for s, state in status.items() if state != NOT_CONSIDERED]
    return {
        "schema_version": "financial_intelligence_domain_coverage_v1",
        "grain": bindings["grain"],
        "row_classification": bindings["row_classification"],
        "certification": "WITHHELD",
        "denominator": {
            "audit_rows": len(status),
            "registry_sources": len(registry_sources),
            "not_considered_candidates": len(status) - len(registry_sources),
            "bound": len(bound),
            "explicitly_unbound": len(unbound),
            "unclassified": len(unclassified),
            "conserved": len(bound) + len(unbound) + len(unclassified) == len(status),
        },
        "unclassified_sources": unclassified,
        "domains_without_registered_source": [
            d for d in domain_ids if per_domain[d]["registered_sources"] == 0
        ],
        "domains_without_materializing_source": [
            d for d in domain_ids if per_domain[d]["materializing_sources"] == 0
        ],
        "sources_in_multiple_domains": sum(1 for ids in bound.values() if len(ids) > 1),
        "domains": per_domain,
        "unbound": unbound,
    }


def render_markdown(coverage: dict[str, Any], audit_sha256: str) -> str:
    den = coverage["denominator"]
    caveat = (
        "This table counts registered sources that are **candidate** inputs to each domain. "
        "It is not a statement about rows, materialized data or certified coverage. "
        "Row classification is OPEN and certification is WITHHELD."
    )
    denominator = (
        f"Denominator: `reports/financial_source_audit.csv` (sha256 `{audit_sha256}`), "
        f"{den['registry_sources']} registry sources plus {den['not_considered_candidates']} "
        f"not-yet-registered candidates. Bound {den['bound']}, explicitly unbound "
        f"{den['explicitly_unbound']}, unclassified {den['unclassified']}."
    )
    overlap = (
        f"A source may feed several domains ({coverage['sources_in_multiple_domains']} do), "
        "so the Registered column does not sum to the denominator."
    )
    lines = [
        "# Financial-intelligence domain coverage v1 (source-level candidates)",
        "",
        "_Generated by `python -m moneysweep.financial_intelligence.coverage`. Do not hand-edit._",
        "",
        caveat,
        "",
        denominator,
        "",
        "| Domain | Name | Priority | Registered | Materializing now | Not yet registered |",
        "|---|---|---|---:|---:|---:|",
    ]
    for domain_id, row in coverage["domains"].items():
        lines.append(
            f"| {domain_id} | {row['name']} | {row['priority']} | {row['registered_sources']} | "
            f"{row['materializing_sources']} | {row['not_considered_candidates']} |"
        )
    lines += [
        "",
        "Domains with no registered source: "
        + (", ".join(coverage["domains_without_registered_source"]) or "none")
        + ".",
        "",
        "Domains with no source producing output now: "
        + (", ".join(coverage["domains_without_materializing_source"]) or "none")
        + ".",
        "",
        overlap,
        "",
        "## Explicitly unbound sources",
        "",
    ]
    lines += [f"- `{source}`: {reason}" for source, reason in coverage["unbound"].items()]
    if coverage["unclassified_sources"]:
        lines += ["", "## Unclassified sources (OPEN)", ""]
        lines += [f"- `{source}`" for source in coverage["unclassified_sources"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the reports are stale")
    args = parser.parse_args(argv)

    ontology = load_ontology()
    bindings = load_bindings()
    audit_path = REPO_ROOT / bindings["denominator"]["path"]
    audit_sha256 = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    coverage = build_coverage(ontology, bindings, read_audit_rows(audit_path))
    coverage["denominator"]["audit_sha256"] = audit_sha256
    coverage["denominator"]["matches_frozen_bindings"] = (
        audit_sha256 == bindings["denominator"]["sha256"]
    )
    rendered_json = json.dumps(coverage, indent=2) + "\n"
    rendered_md = render_markdown(coverage, audit_sha256)
    if args.check:
        stale = (
            not OUT_JSON.exists()
            or OUT_JSON.read_text(encoding="utf-8") != rendered_json
            or not OUT_MD.exists()
            or OUT_MD.read_text(encoding="utf-8") != rendered_md
        )
        print("stale" if stale else "current")
        return 1 if stale else 0
    OUT_JSON.write_text(rendered_json, encoding="utf-8")
    OUT_MD.write_text(rendered_md, encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(REPO_ROOT)} and {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
