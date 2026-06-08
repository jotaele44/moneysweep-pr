"""Build influence graph linking agencies → primes → subs → assets → municipalities.

Reads:
  data/staging/processed/pr_all_awards_master.csv
  data/staging/processed/pr_contracts_master.csv
  data/staging/processed/pr_fema_pa_master.csv
  data/staging/processed/execution/execution_chain_master.csv
  data/staging/processed/entities_resolved.csv
  data/staging/processed/pr_lda_filings.csv
  data/staging/processed/pr_fec_contributions.csv
  data/staging/processed/pr_emma_bonds.csv          (optional)

Writes:
  data/staging/processed/graphs/entity_nodes.csv
  data/staging/processed/graphs/entity_edges.csv
  data/staging/processed/graphs/graph_metrics.csv
  data/staging/processed/graphs/top_25_control_entities.csv
  data/staging/processed/graphs/influence_graph.graphml
  data/staging/processed/graphs/influence_graph.gexf
  data/staging/processed/graphs/influence_graph_summary.json

Usage:
  python3 scripts/influence_graph_builder.py
  python3 scripts/influence_graph_builder.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.maturity_gate import (
    claim_tier,
    load_dataset_to_source_map,
    load_source_maturity,
)

NAME_FIELDS = ["recipient_name", "vendor_name", "award_recipient_name", "prime_recipient_name"]
UEI_FIELDS = ["recipient_uei", "uei", "entity_uei", "prime_uei"]
PARENT_UEI_FIELDS = ["parent_uei", "parent_name", "ultimate_parent_uei", "prime_parent_uei"]
AMOUNT_FIELDS = [
    "obligated_amount",
    "total_obligation",
    "obligation_amount",
    "subaward_amount",
    "amount",
]
AGENCY_FIELDS = ["awarding_agency", "funding_agency", "funding_source", "awarding_sub_agency"]
MUNICIPALITY_FIELDS = ["municipality", "pop_county", "county", "pop_city"]
AWARD_ID_FIELDS = ["award_id", "generated_unique_award_id", "prime_award_id"]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0 or path.suffix.lower() != ".csv":
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _first(row: dict, fields: list[str]) -> str:
    for f in fields:
        v = row.get(f)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _money(row: dict) -> float:
    for f in AMOUNT_FIELDS:
        v = row.get(f)
        if v not in (None, ""):
            try:
                return float(str(v).replace(",", "").replace("$", ""))
            except Exception:
                pass
    return 0.0


def _add_edge(
    edges: list,
    nodes: dict,
    source: str,
    target: str,
    edge_type: str,
    weight: float = 1.0,
    source_dataset: str = "",
    evidence_id: str = "",
    confidence: float = 0.5,
    source_type: str = "entity",
    target_type: str = "entity",
    *,
    maturity: dict[str, str] | None = None,
    dataset_map: dict[str, str] | None = None,
) -> None:
    if not source or not target:
        return
    nodes.setdefault(source, {"id": source, "label": source, "node_type": source_type})
    nodes.setdefault(target, {"id": target, "label": target, "node_type": target_type})
    tier = (
        claim_tier([source_dataset], maturity or {}, dataset_map or {})
        if source_dataset
        else "blocked"
    )
    edges.append(
        {
            "source": source,
            "target": target,
            "edge_type": edge_type,
            "weight": round(float(weight), 2),
            "source_dataset": source_dataset,
            "evidence_id": evidence_id,
            "confidence": round(float(confidence), 3),
            "claim_tier": tier,
            "manual_review_required": confidence < 0.8,
        }
    )


def _load_entity_index(root: Path) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for row in _read_csv(root / "data/staging/processed/entities_resolved.csv"):
        uei = row.get("entity_uei", "").strip()
        name = row.get("normalized_name", "").strip()
        for key in filter(None, [uei, name]):
            idx.setdefault(key, row)
    return idx


def _resolve_parent(uei: str, name: str, entity_idx: dict[str, dict]) -> str:
    rec = entity_idx.get(uei) or entity_idx.get(name)
    if rec:
        return rec.get("parent_uei") or rec.get("parent_name") or ""
    return ""


def _build_edges(root: Path) -> tuple[dict, list]:
    proc = root / "data/staging/processed"
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    entity_idx = _load_entity_index(root)
    maturity = load_source_maturity(root)
    dataset_map = load_dataset_to_source_map(root)

    def add(*args, **kwargs):
        _add_edge(*args, maturity=maturity, dataset_map=dataset_map, **kwargs)

    # Awards: agency → prime, parent → prime, prime → municipality
    for path in [
        proc / "pr_all_awards_master.csv",
        proc / "pr_contracts_master.csv",
        proc / "pr_fema_pa_master.csv",
    ]:
        for row in _read_csv(path):
            agency = _first(row, AGENCY_FIELDS)
            recip = _first(row, NAME_FIELDS)
            uei = _first(row, UEI_FIELDS)
            parent = _first(row, PARENT_UEI_FIELDS) or _resolve_parent(uei, recip, entity_idx)
            aid = _first(row, AWARD_ID_FIELDS)
            amt = _money(row)
            muni = _first(row, MUNICIPALITY_FIELDS)

            add(
                edges,
                nodes,
                agency,
                recip,
                "awards_to",
                amt,
                path.name,
                aid,
                0.75,
                "agency",
                "prime",
            )
            if parent:
                add(
                    edges,
                    nodes,
                    parent,
                    recip,
                    "parent_of",
                    1.0,
                    path.name,
                    aid,
                    0.90,
                    "parent_entity",
                    "prime",
                )
            if muni:
                add(
                    edges,
                    nodes,
                    recip,
                    muni,
                    "located_in",
                    1.0,
                    path.name,
                    aid,
                    0.60,
                    "prime",
                    "municipality",
                )

    # Execution chains: prime → sub, sub → asset/project, asset → municipality
    for row in _read_csv(proc / "execution" / "execution_chain_master.csv"):
        prime = _first(row, ["prime_parent_uei", "prime_name"])
        sub = _first(row, ["sub_parent_uei", "sub_name"])
        aid = _first(row, ["award_id", "subaward_id", "chain_id"])
        amt = _money(row)
        conf = float(row.get("link_confidence") or 0.5)
        muni = _first(row, MUNICIPALITY_FIELDS)
        asset = _first(row, ["asset_id", "project_id"])

        add(
            edges,
            nodes,
            prime,
            sub,
            "subawards_to",
            amt,
            "execution_chain_master.csv",
            aid,
            conf,
            "prime",
            "subcontractor",
        )
        if asset:
            add(
                edges,
                nodes,
                sub or prime,
                asset,
                "executes_project",
                amt,
                "execution_chain_master.csv",
                aid,
                conf,
                "subcontractor",
                "asset",
            )
        if muni:
            src_node = asset or sub or prime
            add(
                edges,
                nodes,
                src_node,
                muni,
                "located_in",
                1.0,
                "execution_chain_master.csv",
                aid,
                0.60,
                "asset",
                "municipality",
            )

    # LDA lobbying: registrant → client
    for row in _read_csv(proc / "pr_lda_filings.csv"):
        registrant = _first(row, ["registrant_name", "registrant"])
        client = _first(row, ["client_name", "client"])
        filing_id = _first(row, ["filing_uuid", "filing_id"])
        amt = _money(row) or 1.0
        add(
            edges,
            nodes,
            registrant,
            client,
            "lobbies_for",
            amt,
            "pr_lda_filings.csv",
            filing_id,
            0.65,
            "lobbying_registrant",
            "lobbying_client",
        )

    # FEC contributions: contributor → committee
    for row in _read_csv(proc / "pr_fec_contributions.csv"):
        contributor = _first(row, ["contributor_name", "donor", "name", "entity_name"])
        committee = _first(row, ["committee_name", "recipient_committee", "committee"])
        txn = _first(row, ["transaction_id", "report_year"])
        amt = _money(row) or 1.0
        add(
            edges,
            nodes,
            contributor,
            committee,
            "contributes_to",
            amt,
            "pr_fec_contributions.csv",
            txn,
            0.55,
            "person_or_entity",
            "campaign_committee",
        )

    # EMMA bonds: issuer → underwriter, issuer → asset
    for path in [proc / "pr_emma_bonds.csv", proc / "pr_emma_underwriters.csv"]:
        for row in _read_csv(path):
            issuer = _first(row, ["issuer", "issuer_name"])
            under = _first(row, ["underwriter", "dealer", "underwriter_name"])
            cusip = _first(row, ["cusip", "issue_id", "series"])
            par = _money(row)
            asset = _first(row, ["project_asset", "asset_id", "project_id"])
            add(
                edges,
                nodes,
                issuer,
                under,
                "underwrites",
                par,
                path.name,
                cusip,
                0.80,
                "bond_issuer",
                "underwriter",
            )
            if asset:
                add(
                    edges,
                    nodes,
                    issuer,
                    asset,
                    "funds_asset",
                    par,
                    path.name,
                    cusip,
                    0.65,
                    "bond_issuer",
                    "asset",
                )

    # NGO / OSFL layer: funder → NGO, NGO → municipality, NGO → asset, sponsor → NGO.
    # Confidence in the NGO outputs is on a 0-100 scale; rescale to 0-1 here.
    ngo_dir = proc / "ngos"
    for row in _read_csv(ngo_dir / "ngo_funding_edges.csv"):
        funder = _first(row, ["source_entity", "funding_agency"])
        ngo_id = _first(row, ["target_ngo_id"])
        ngo_name = _first(row, ["target_name"])
        award_id = _first(row, ["award_id", "edge_id"])
        amt = _money(row)
        muni = _first(row, MUNICIPALITY_FIELDS)
        try:
            conf = min(0.95, float(row.get("confidence") or 0) / 100.0)
        except Exception:
            conf = 0.45
        if ngo_id and ngo_name:
            nodes.setdefault(ngo_id, {"id": ngo_id, "label": ngo_name, "node_type": "ngo"})
        if funder and ngo_id:
            add(
                edges,
                nodes,
                funder,
                ngo_id,
                "funds_ngo",
                amt,
                "ngo_funding_edges.csv",
                award_id,
                conf,
                "agency",
                "ngo",
            )
        if ngo_id and muni:
            add(
                edges,
                nodes,
                ngo_id,
                muni,
                "located_in",
                1.0,
                "ngo_funding_edges.csv",
                award_id,
                0.60,
                "ngo",
                "municipality",
            )

    for row in _read_csv(ngo_dir / "ngo_asset_edges.csv"):
        ngo_id = _first(row, ["ngo_id"])
        asset = _first(row, ["asset_id"])
        muni = _first(row, MUNICIPALITY_FIELDS)
        try:
            conf = min(0.95, float(row.get("confidence") or 0) / 100.0)
        except Exception:
            conf = 0.55
        if ngo_id and asset:
            add(
                edges,
                nodes,
                ngo_id,
                asset,
                "executes_project",
                1.0,
                "ngo_asset_edges.csv",
                asset,
                conf,
                "ngo",
                "asset",
            )
        if asset and muni:
            add(
                edges,
                nodes,
                asset,
                muni,
                "located_in",
                1.0,
                "ngo_asset_edges.csv",
                asset,
                0.60,
                "asset",
                "municipality",
            )

    for row in _read_csv(ngo_dir / "ngo_fiscal_sponsor_edges.csv"):
        sponsor = _first(row, ["sponsor_ngo_id"])
        sponsored = _first(row, ["sponsored_entity"])
        try:
            conf = min(0.95, float(row.get("confidence") or 0) / 100.0)
        except Exception:
            conf = 0.70
        if sponsor and sponsored:
            add(
                edges,
                nodes,
                sponsor,
                sponsored,
                "fiscal_sponsor_of",
                1.0,
                "ngo_fiscal_sponsor_edges.csv",
                "",
                conf,
                "ngo",
                "ngo",
            )

    return nodes, edges


def _compute_metrics(nodes: dict, edges: list) -> list[dict]:
    CONTRACT_TYPES = {"awards_to", "subawards_to", "underwrites", "funds_asset"}
    met: dict[str, dict] = {}
    tier_seen: dict[str, set[str]] = {}
    for e in edges:
        for n in [e["source"], e["target"]]:
            if n not in met:
                met[n] = {
                    "node": n,
                    "node_type": nodes.get(n, {}).get("node_type", "entity"),
                    "degree": 0,
                    "weighted_degree": 0.0,
                    "contract_value_weight": 0.0,
                    "manual_review_edges": 0,
                    "claim_tier": "observed",
                }
                tier_seen[n] = set()
            m = met[n]
            m["degree"] += 1
            m["weighted_degree"] += float(e.get("weight") or 0)
            if e.get("edge_type") in CONTRACT_TYPES:
                m["contract_value_weight"] += float(e.get("weight") or 0)
            if str(e.get("manual_review_required")).lower() == "true":
                m["manual_review_edges"] += 1
            edge_tier = e.get("claim_tier") or "blocked"
            tier_seen[n].add(edge_tier)
    # Each node's tier is the worst tier across its incident edges.
    for node, tiers in tier_seen.items():
        if "blocked" in tiers:
            met[node]["claim_tier"] = "blocked"
        elif "linked" in tiers:
            met[node]["claim_tier"] = "linked"
        else:
            met[node]["claim_tier"] = "observed"
    return list(met.values())


def build_graph(root: Path) -> dict[str, Any]:
    nodes, edges = _build_edges(root)
    out = root / "data/staging/processed/graphs"
    out.mkdir(parents=True, exist_ok=True)

    metrics = _compute_metrics(nodes, edges)
    top25 = sorted(metrics, key=lambda r: (-r["contract_value_weight"], r["node"]))[:25]

    _write_csv(out / "entity_nodes.csv", list(nodes.values()))
    _write_csv(out / "entity_edges.csv", edges)
    _write_csv(out / "graph_metrics.csv", metrics)
    _write_csv(out / "top_25_control_entities.csv", top25)

    graphml_written = gexf_written = False
    try:
        import networkx as nx

        G: nx.MultiDiGraph = nx.MultiDiGraph()
        for n, attrs in nodes.items():
            G.add_node(n, **attrs)
        for i, e in enumerate(edges):
            G.add_edge(
                e["source"],
                e["target"],
                key=f"e{i}",
                **{k: v for k, v in e.items() if k not in ("source", "target")},
            )
        nx.write_graphml(G, out / "influence_graph.graphml")
        nx.write_gexf(G, out / "influence_graph.gexf")
        graphml_written = gexf_written = True
    except Exception:
        pass

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "graphml_written": graphml_written,
        "gexf_written": gexf_written,
        "top_25_written": len(top25) > 0,
        "top_25_path": "data/staging/processed/graphs/top_25_control_entities.csv",
        "outputs": [
            "data/staging/processed/graphs/entity_nodes.csv",
            "data/staging/processed/graphs/entity_edges.csv",
            "data/staging/processed/graphs/graph_metrics.csv",
            "data/staging/processed/graphs/top_25_control_entities.csv",
            "data/staging/processed/graphs/influence_graph.graphml",
            "data/staging/processed/graphs/influence_graph.gexf",
        ],
    }
    (out / "influence_graph_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    a = p.parse_args(argv)
    print(json.dumps(build_graph(Path(a.root)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
