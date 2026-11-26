"""Loader and structural gates for the 25-domain financial-intelligence ontology.

The ontology is a classification overlay. It defines no entity, relationship or
amount of its own; every domain names the existing primitives it reuses.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from moneysweep.entity_network import NodeKind, RelationshipFamily

from ._common import BASELINE_YEAR, FinancialIntelligenceError
from .continuity import DIMENSIONS
from .transactions import FlowCharacter, FlowDirection

REPO_ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY_PATH = REPO_ROOT / "registries" / "financial_intelligence_ontology_v1.json"
SCHEMA_VERSION = "financial_intelligence_ontology_v1"
DOMAIN_IDS = tuple(f"MS{number:02d}" for number in range(1, 26))
MONEY_FLOW_BINDING = "MONEY_FLOW"
SELF_ALIAS = "moneysweep-pr"


class OntologyError(FinancialIntelligenceError):
    """The ontology registry breaks one of its own structural rules."""


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise OntologyError(f"duplicate {label}")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise OntologyError(message)


def validate_ontology(data: dict[str, Any]) -> None:
    """Fail closed on any structural drift in the registry."""
    _expect(data.get("schema_version") == SCHEMA_VERSION, "unexpected schema_version")
    if data.get("production_adoption") != "BLOCKED":
        _expect(
            data.get("certification") == "PASS",
            "production adoption cannot be unblocked while certification is withheld",
        )

    foundations = [item["id"] for item in data["foundations"]]
    _unique(foundations, "foundation id")
    known_foundations = set(foundations)

    domains = data["domains"]
    _expect(tuple(d["id"] for d in domains) == DOMAIN_IDS, "domains must be MS01..MS25 in order")
    _unique([d["name"] for d in domains], "domain name")
    priorities = set(data["priority_levels"])
    for domain in domains:
        _expect(domain["priority"] in priorities, f"{domain['id']}: unknown priority")
        _expect(bool(domain["reuses_foundations"]), f"{domain['id']}: reuses no foundation")
        _expect(
            set(domain["reuses_foundations"]) <= known_foundations,
            f"{domain['id']}: unknown foundation",
        )

    classes = data["foreign_connection_classes"]
    _expect(len(classes) == 9, "foreign connections need exactly nine relationship classes")
    _unique([c["id"] for c in classes], "foreign connection class id")
    families = {family.value for family in RelationshipFamily}
    for item in classes:
        _expect(
            item["kernel_binding"] in families | {MONEY_FLOW_BINDING},
            f"{item['id']}: unknown kernel binding",
        )

    flow = data["flow_model"]
    axis = {item["id"] for item in flow["geographic_axis"]}
    _expect(
        axis
        == {
            FlowDirection.INBOUND.value,
            FlowDirection.OUTBOUND.value,
            FlowDirection.INTERNAL.value,
        },
        "geographic axis drifted from FlowDirection",
    )
    characters = {item["id"] for item in flow["characters"]}
    _expect(
        characters == {c.value for c in FlowCharacter}, "flow characters drifted from FlowCharacter"
    )

    node_kinds = {kind.value for kind in NodeKind}
    for group in data["entity_universe"]:
        for kind in group["kinds"]:
            _expect(kind["node_kind"] in node_kinds, f"{kind['name']}: unknown node kind")

    registry_dimensions = {d["id"]: frozenset(d["states"]) for d in data["continuity_dimensions"]}
    _expect(registry_dimensions == DIMENSIONS, "continuity dimensions drifted from the model")

    scope = data["historical_scope"]
    _expect(scope["baseline_year"] == BASELINE_YEAR, "baseline year drifted from the model")
    _expect(
        scope["periods_are_mutually_exclusive"] is False, "periods are analytical, not exclusive"
    )
    periods = scope["periods"]
    starts = [p["start_year"] for p in periods]
    _expect(starts == sorted(starts) and starts[0] == BASELINE_YEAR, "period starts out of order")
    _expect(
        [p["end_year"] is None for p in periods] == [False] * (len(periods) - 1) + [True],
        "only the last period is open-ended",
    )

    capabilities = data["capabilities"]
    _expect(len(capabilities) == 20, "exactly twenty analytical capabilities are specified")
    _unique([c["id"] for c in capabilities], "capability id")
    for capability in capabilities:
        _expect(bool(capability["guardrail"].strip()), f"{capability['id']}: missing guardrail")
        _expect(
            set(capability["requires_foundations"]) <= known_foundations,
            f"{capability['id']}: unknown foundation",
        )

    infrastructure = data["infrastructure_classes"]
    _expect(len(infrastructure) == 14, "exactly fourteen infrastructure classes are specified")
    for item in infrastructure:
        owner = item["identity_owner_candidate"]
        _expect(owner != SELF_ALIAS, f"{item['id']}: MoneySweep must not own an asset registry")
        _expect(
            (owner is None) == (item["owner_state"] == "UNASSIGNED"),
            f"{item['id']}: owner and owner_state disagree",
        )

    ranks = [tier["rank"] for tier in data["source_authority_hierarchy"]]
    _expect(ranks == list(range(1, len(ranks) + 1)), "authority ranks must be contiguous")
    for tier in data["source_authority_hierarchy"]:
        if tier["evidence_tier"] == "T4":
            _expect(not tier["may_establish"], f"{tier['id']}: secondary sources are leads only")


def load_ontology(path: Path | None = None) -> dict[str, Any]:
    data = json.loads((path or ONTOLOGY_PATH).read_text(encoding="utf-8"))
    validate_ontology(data)
    return data


def unresolved_foundation_bindings(data: dict[str, Any], root: Path = REPO_ROOT) -> list[str]:
    """Return every foundation or domain reference that no longer resolves."""
    missing: list[str] = []
    for foundation in data["foundations"]:
        module_name = foundation.get("module")
        if module_name:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                missing.append(module_name)
                continue
            missing.extend(
                f"{module_name}.{symbol}"
                for symbol in foundation.get("symbols", [])
                if not hasattr(module, symbol)
            )
        missing.extend(p for p in foundation.get("paths", []) if not (root / p).exists())
    for domain in data["domains"]:
        missing.extend(p for p in domain["existing_assets"] if not (root / p).exists())
    return missing
