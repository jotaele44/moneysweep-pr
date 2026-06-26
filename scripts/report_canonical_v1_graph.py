"""Generate a read-only legibility summary of the Canonical v1 graph.

Purely derived: this reporter reads the committed ``data/canonical_v1`` tables
and emits node/edge/evidence/coverage/connectivity statistics. It asserts **no
new sourced claims** — it only counts and describes what is already in the
graph — so it is safe to run autonomously between source-backed ingests.

Phrasing follows ``docs/CLAIM_LANGUAGE_POLICY.md`` (descriptive, non-conclusive),
and every output carries the production gate label (``NON_PRODUCTION_DIAGNOSTIC``).

Roadmap: graph legibility (supports WS-O coverage metrics / WS-P readiness).
Stdlib only.

CLI::

    python scripts/report_canonical_v1_graph.py --root .
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.validation.canonical_v1_schema import load_all_tables

REPO_ROOT = Path(__file__).resolve().parents[1]
MD_OUT = "reports/canonical_v1_graph_summary.md"
JSON_OUT = "reports/canonical_v1_graph_summary.json"
GATE_LABEL = "NON_PRODUCTION_DIAGNOSTIC"

# Node tables that carry graph nodes (evidence/review_queue are not graph nodes).
NODE_TABLES = (
    "people",
    "entities",
    "roles",
    "contracts",
    "projects",
    "debt_instruments",
    "lobbying_records",
    "funding_sources",
    "properties",
    "municipalities",
)


def summarize(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    tables = load_all_tables(root)

    node_counts = {t: len(tables.get(t, [])) for t in NODE_TABLES}
    total_nodes = sum(node_counts.values())

    edges = tables.get("edges", [])
    edge_type_counts: dict[str, int] = defaultdict(int)
    for e in edges:
        edge_type_counts[(e.get("edge_type") or "").strip()] += 1

    # Evidence tier + review-status distribution.
    evidence = tables.get("evidence", [])
    tier_counts: dict[str, int] = defaultdict(int)
    status_counts: dict[str, int] = defaultdict(int)
    accepted_ev: set[str] = set()
    for ev in evidence:
        tier_counts[(ev.get("evidence_tier") or "").strip()] += 1
        st = (ev.get("review_status") or "").strip()
        status_counts[st] += 1
        if st == "accepted":
            eid = (ev.get("evidence_id") or "").strip()
            if eid:
                accepted_ev.add(eid)

    # Edge evidence coverage: share of edges backed by an accepted evidence row.
    edges_with_accepted = sum(
        1 for e in edges if (e.get("evidence_id") or "").strip() in accepted_ev
    )
    coverage_pct = round(100.0 * edges_with_accepted / len(edges), 2) if edges else 0.0

    # Degree over the node graph (edges reference node ids on either end).
    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        s = (e.get("source_node_id") or "").strip()
        t = (e.get("target_node_id") or "").strip()
        if s:
            degree[s] += 1
        if t:
            degree[t] += 1
    connected_nodes = len(degree)
    top_degree = sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))[:10]

    return {
        "gate": GATE_LABEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_counts": dict(node_counts),
        "total_nodes": total_nodes,
        "edge_count": len(edges),
        "edge_type_counts": dict(sorted(edge_type_counts.items())),
        "evidence_count": len(evidence),
        "evidence_tier_counts": dict(sorted(tier_counts.items())),
        "evidence_review_status_counts": dict(sorted(status_counts.items())),
        "edge_evidence_coverage_pct": coverage_pct,
        "edges_backed_by_accepted_evidence": edges_with_accepted,
        "connected_node_count": connected_nodes,
        "review_queue_open": sum(
            1
            for r in tables.get("review_queue", [])
            if (r.get("status") or "").strip() in ("open", "in_review")
        ),
        "top_degree_nodes": [{"node_id": n, "degree": d} for n, d in top_degree],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Canonical v1 Graph Summary",
        "",
        f"**Gate:** `{summary['gate']}` · **Generated:** {summary['generated_at']}",
        "",
        "_Descriptive, derived summary of the committed canonical_v1 tables. "
        "Asserts no new sourced claims; every figure is a count over existing, "
        "evidence-backed rows. Phrasing follows `docs/CLAIM_LANGUAGE_POLICY.md`._",
        "",
        f"## Nodes ({summary['total_nodes']} total)",
        "",
        "| Table | Count |",
        "|-------|-------|",
    ]
    for t, c in summary["node_counts"].items():
        lines.append(f"| `{t}` | {c} |")
    lines += [
        "",
        f"## Edges ({summary['edge_count']} total)",
        "",
        "| edge_type | Count |",
        "|-----------|-------|",
    ]
    for et, c in summary["edge_type_counts"].items():
        lines.append(f"| `{et}` | {c} |")
    lines += [
        "",
        "## Evidence",
        "",
        f"- Rows: **{summary['evidence_count']}**",
        f"- Tier distribution: {summary['evidence_tier_counts']}",
        f"- Review status: {summary['evidence_review_status_counts']}",
        f"- Edge evidence coverage: **{summary['edge_evidence_coverage_pct']}%** "
        f"({summary['edges_backed_by_accepted_evidence']}/{summary['edge_count']} "
        "edges backed by an accepted evidence row)",
        "",
        "## Connectivity",
        "",
        f"- Nodes touched by ≥1 edge: **{summary['connected_node_count']}**",
        f"- Open review-queue items: {summary['review_queue_open']}",
        "",
        "### Highest-degree nodes (record shows most edge endpoints)",
        "",
        "| node_id | degree |",
        "|---------|--------|",
    ]
    for nd in summary["top_degree_nodes"]:
        lines.append(f"| `{nd['node_id']}` | {nd['degree']} |")
    lines.append("")
    return "\n".join(lines)


def write_reports(summary: dict[str, Any], root: Path | None = None) -> None:
    root = root or REPO_ROOT
    (root / JSON_OUT).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (root / MD_OUT).write_text(render_markdown(summary), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize the canonical_v1 graph (read-only).")
    parser.add_argument("--root", default=".")
    parser.add_argument("--print", action="store_true", help="Print the JSON summary to stdout.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    summary = summarize(root)
    write_reports(summary, root)
    if args.print:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"wrote {MD_OUT} and {JSON_OUT} "
            f"({summary['total_nodes']} nodes, {summary['edge_count']} edges)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
