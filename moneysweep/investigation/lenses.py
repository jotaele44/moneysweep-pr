"""Validate the frozen research denominator without certifying research results.

Development infrastructure only. Callers cannot replace mandatory gates, waive a
lens, or turn a registry count into a software/source/finding certificate.
"""
from __future__ import annotations

LENS_IDS = (
    "family_lineages", "corporate_heritage", "ownership_control",
    "institutional_ties", "political_connections", "lobbying_representation",
    "campaign_finance", "contracts_procurement", "grants_assistance",
    "financial_relationships", "property_assets", "nonprofit_philanthropy",
    "professional_networks", "government_regulatory", "judicial_administrative",
    "media_information", "events_communications", "policy_legislative",
    "geographic_relationships", "historical_development", "cross_border_territorial",
    "conflicts_disclosures", "network_structure", "evidence_counterevidence",
)
GATES = (
    "scope", "identity", "provenance", "temporal_alignment", "contradictions",
    "falsification", "persistence_authorization", "gui", "export_replay", "recovery",
)
STATES = frozenset({"PASS", "FAIL", "OPEN", "BLOCKED", "UNATTEMPTED", "UNRESOLVED"})


def validate_registry(registry: object) -> None:
    """Reject missing/extra lenses, weak contracts and unsupported readiness claims."""
    if not isinstance(registry, dict):
        raise ValueError("registry must be an object")
    if set(registry) != {"schema_version", "repository", "source_revision", "lenses"}:
        raise ValueError("invalid registry fields")
    if registry["schema_version"] != "moneysweep.investigation-lenses/v1":
        raise ValueError("unsupported registry version")
    if registry["repository"] != "jotaele44/moneysweep-pr":
        raise ValueError("wrong repository binding")
    revision = registry["source_revision"]
    if not isinstance(revision, str) or len(revision) != 40 or any(
        c not in "0123456789abcdef" for c in revision
    ):
        raise ValueError("source revision must be a full lowercase git SHA")
    lenses = registry["lenses"]
    if not isinstance(lenses, list) or len(lenses) != len(LENS_IDS):
        raise ValueError("lens denominator changed")
    seen = set()
    for lens in lenses:
        if not isinstance(lens, dict) or set(lens) != {
            "id", "question", "predicates", "source_families", "falsification",
            "implementation_state", "source_coverage_state", "finding_state",
            "owner", "gates",
        }:
            raise ValueError("invalid lens fields")
        lid = lens["id"]
        if not isinstance(lid, str) or lid not in LENS_IDS or lid in seen:
            raise ValueError("unknown or duplicate lens")
        seen.add(lid)
        if lens["owner"] != "moneysweep-pr":
            raise ValueError("external development requires explicit scope decision")
        for name in ("question", "falsification"):
            if not isinstance(lens[name], str) or not lens[name].strip():
                raise ValueError(f"missing {name}")
        for name in ("predicates", "source_families"):
            values = lens[name]
            if not isinstance(values, list) or not values or any(
                not isinstance(v, str) or not v.strip() for v in values
            ) or len(set(values)) != len(values):
                raise ValueError(f"invalid {name}")
        for name in ("implementation_state", "source_coverage_state", "finding_state"):
            if not isinstance(lens[name], str) or lens[name] not in STATES:
                raise ValueError(f"invalid {name}")
        gates = lens["gates"]
        if not isinstance(gates, dict) or set(gates) != set(GATES):
            raise ValueError("mandatory gates cannot be omitted or waived")
        for gate in gates.values():
            if not isinstance(gate, dict) or set(gate) != {"state", "evidence_refs"}:
                raise ValueError("invalid gate record")
            if not isinstance(gate["state"], str) or gate["state"] not in STATES:
                raise ValueError("invalid gate state")
            refs = gate["evidence_refs"]
            if not isinstance(refs, list) or any(
                not isinstance(ref, str) or not ref.strip() for ref in refs
            ) or len(set(refs)) != len(refs):
                raise ValueError("invalid gate evidence")
            if gate["state"] == "PASS" and not refs:
                raise ValueError("PASS requires evidence references")
        if lens["implementation_state"] == "PASS" and any(
            gate["state"] != "PASS" for gate in gates.values()
        ):
            raise ValueError("implementation PASS requires all applicable gates")


def summarize_registry(registry: object) -> dict:
    """Account for all lenses; deliberately never emit a readiness certificate.

Evidence references are syntactically checked, not independently verified here.
Source coverage and proposition validity require their own bounded adjudication.
"""
    validate_registry(registry)
    lenses = registry["lenses"]
    counts = {}
    for axis in ("implementation_state", "source_coverage_state", "finding_state"):
        counts[axis] = {state: sum(lens[axis] == state for lens in lenses) for state in sorted(STATES)}
    return {
        "declared_lenses": len(lenses),
        "required_lenses": len(LENS_IDS),
        "registry_accounted": True,
        "states": counts,
        "readiness": "UNRESOLVED",
        "reason": "Registry accounting is not independent gate or finding verification",
    }
