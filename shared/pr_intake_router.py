"""Shared Puerto Rico intake router.

This module loads ``config/pr_intake_domain_router.yaml`` and routes raw Puerto
Rico-relevant intake items into canonical Contract-Sweeper or spiderweb-pr
lanes. It is intentionally deterministic: no LLM calls, no network access, and
no silent dropping of records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set
import hashlib
import json
import re
import unicodedata

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency guard
    raise RuntimeError(
        "PyYAML is required to load pr_intake_domain_router.yaml. "
        "Install with: pip install PyYAML"
    ) from exc


CONTRACT_REPO = "Contract-Sweeper"
SPIDERWEB_REPO = "spiderweb-pr"

CONTRACT_DOMAINS = {
    "politics",
    "finance",
    "public_funding",
    "procurement",
    "contracts",
    "lobbying",
    "municipal_finance",
    "budget_authority",
    "agency_authority",
    "public_corporation_finance",
    "contractor_recipient_chains",
}

SPIDERWEB_DOMAINS = {
    "geography_gis",
    "infrastructure_footprint",
    "subsurface_hydro",
    "aviation_activity",
    "maritime_activity",
    "federal_military_activity",
    "environment_weather",
    "science_dataset",
    "physical_observation",
    "poi_aoi_corridor_candidate",
}

INACCESSIBLE_STATUSES = {"source_inaccessible", "inaccessible", "error", "not_found"}
BLOCKED_STATUSES = {"blocked_or_paywalled", "blocked", "paywalled", "login_required"}
METADATA_ONLY_STATUSES = {"metadata_only_archived", "metadata_only"}


@dataclass(frozen=True)
class RouterConfig:
    """Parsed router configuration."""

    raw: Mapping[str, Any]
    final_status_values: Set[str]
    routing_rules: Sequence[Mapping[str, Any]]
    dual_route_conditions: Sequence[Mapping[str, Any]]
    required_common_fields: Sequence[str]
    validation_gates: Sequence[str]
    primary_repo: str
    paired_repo: str


@dataclass
class RouteResult:
    """Routing decision for one raw intake item."""

    source_item_id: str
    domains: List[str]
    matched_rules: List[str]
    final_status: str
    canonical_repo: Optional[str]
    derivative_repo: Optional[str]
    output_tables: Dict[str, List[str]] = field(default_factory=dict)
    contract_sweeper_derivative: Optional[Dict[str, Any]] = None
    spiderweb_pr_derivative: Optional[Dict[str, Any]] = None
    review_reason: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_item_id": self.source_item_id,
            "domains": self.domains,
            "matched_rules": self.matched_rules,
            "final_status": self.final_status,
            "canonical_repo": self.canonical_repo,
            "derivative_repo": self.derivative_repo,
            "output_tables": self.output_tables,
            "contract_sweeper_derivative": self.contract_sweeper_derivative,
            "spiderweb_pr_derivative": self.spiderweb_pr_derivative,
            "review_reason": self.review_reason,
            "validation_errors": self.validation_errors,
        }


class IntakeRouterError(ValueError):
    """Raised when router input/configuration violates a hard gate."""


def load_router_config(path: str | Path = "config/pr_intake_domain_router.yaml") -> RouterConfig:
    """Load and validate router YAML config."""

    config_path = Path(path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise IntakeRouterError(f"Router config is not a mapping: {config_path}")

    required_keys = [
        "final_status_values",
        "routing_rules",
        "dual_route_conditions",
        "required_common_fields",
        "validation_gates",
    ]
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise IntakeRouterError(f"Router config missing required keys: {missing}")

    return RouterConfig(
        raw=data,
        final_status_values=set(data.get("final_status_values") or []),
        routing_rules=list(data.get("routing_rules") or []),
        dual_route_conditions=list(data.get("dual_route_conditions") or []),
        required_common_fields=list(data.get("required_common_fields") or []),
        validation_gates=list(data.get("validation_gates") or []),
        primary_repo=str(data.get("primary_repo") or ""),
        paired_repo=str(data.get("paired_repo") or ""),
    )


def route_raw_items(
    raw_items: Iterable[Mapping[str, Any]],
    config: RouterConfig,
    *,
    strict: bool = True,
) -> List[RouteResult]:
    """Route multiple raw items and enforce zero-loss status assignment."""

    results = [route_raw_item(item, config, strict=strict) for item in raw_items]
    missing_status = [r.source_item_id for r in results if not r.final_status]
    if missing_status:
        raise IntakeRouterError(f"Zero-loss failure: items without final status: {missing_status}")
    return results


def route_raw_item(
    raw_item: Mapping[str, Any],
    config: RouterConfig,
    *,
    strict: bool = True,
) -> RouteResult:
    """Classify and route one raw item."""

    source_item_id = str(raw_item.get("source_item_id") or raw_item.get("item_id") or "UNKNOWN")
    status_override = _status_override(raw_item)
    domains, matched_rules, output_tables = classify_raw_item(raw_item, config)

    if status_override:
        result = RouteResult(
            source_item_id=source_item_id,
            domains=sorted(domains),
            matched_rules=matched_rules,
            final_status=status_override,
            canonical_repo=None,
            derivative_repo=None,
            output_tables={},
            review_reason=f"Input access/archive status forced final status: {status_override}",
        )
        _validate_result(result, raw_item, config, strict=strict)
        return result

    canonical_repo, derivative_repo, final_status, review_reason = _decide_route(domains, config)

    result = RouteResult(
        source_item_id=source_item_id,
        domains=sorted(domains),
        matched_rules=matched_rules,
        final_status=final_status,
        canonical_repo=canonical_repo,
        derivative_repo=derivative_repo,
        output_tables=output_tables,
        review_reason=review_reason,
    )

    if canonical_repo == CONTRACT_REPO or derivative_repo == CONTRACT_REPO:
        result.contract_sweeper_derivative = _build_derivative(
            raw_item,
            target_repo=CONTRACT_REPO,
            canonical_repo=canonical_repo,
            domains=domains,
            final_status=final_status,
            output_tables=output_tables.get(CONTRACT_REPO, []),
        )

    if canonical_repo == SPIDERWEB_REPO or derivative_repo == SPIDERWEB_REPO:
        result.spiderweb_pr_derivative = _build_derivative(
            raw_item,
            target_repo=SPIDERWEB_REPO,
            canonical_repo=canonical_repo,
            domains=domains,
            final_status=final_status,
            output_tables=output_tables.get(SPIDERWEB_REPO, []),
        )

    _validate_result(result, raw_item, config, strict=strict)
    return result


def classify_raw_item(
    raw_item: Mapping[str, Any],
    config: RouterConfig,
) -> tuple[Set[str], List[str], Dict[str, List[str]]]:
    """Return detected domains, matched rule IDs, and output table hints."""

    text = _normalized_search_text(raw_item)
    domains: Set[str] = set()
    matched_rules: List[str] = []
    output_tables: Dict[str, List[str]] = {CONTRACT_REPO: [], SPIDERWEB_REPO: []}

    for rule in config.routing_rules:
        keywords = rule.get("keywords") or []
        if any(_keyword_in_text(keyword, text) for keyword in keywords):
            rule_id = str(rule.get("rule_id") or "UNKNOWN_RULE")
            matched_rules.append(rule_id)
            domains.update(str(domain) for domain in (rule.get("domains") or []))
            repo = str(rule.get("canonical_repo") or "")
            tables = [str(t) for t in (rule.get("output_tables") or [])]
            if repo in output_tables:
                output_tables[repo].extend(tables)

    for repo in list(output_tables):
        output_tables[repo] = sorted(set(output_tables[repo]))

    return domains, matched_rules, output_tables


def _decide_route(domains: Set[str], config: RouterConfig) -> tuple[Optional[str], Optional[str], str, Optional[str]]:
    if not domains:
        return None, None, "manual_review_required", "No configured domain keywords matched raw item."

    has_contract = bool(domains & CONTRACT_DOMAINS)
    has_spiderweb = bool(domains & SPIDERWEB_DOMAINS)

    if has_contract and not has_spiderweb:
        return CONTRACT_REPO, None, "routed_contract_sweeper", None
    if has_spiderweb and not has_contract:
        return SPIDERWEB_REPO, None, "routed_spiderweb_pr", None

    for condition in config.dual_route_conditions:
        required_domains = set(condition.get("if_domains_include") or [])
        if required_domains and required_domains.issubset(domains):
            canonical_repo = str(condition.get("canonical_repo") or "")
            derivative_repo = str(condition.get("derivative_repo") or "")
            if canonical_repo == CONTRACT_REPO:
                return CONTRACT_REPO, derivative_repo or SPIDERWEB_REPO, "dual_routed_contract_primary", None
            if canonical_repo == SPIDERWEB_REPO:
                return SPIDERWEB_REPO, derivative_repo or CONTRACT_REPO, "dual_routed_spiderweb_primary", None

    # Mixed signal without an explicit configured condition. Prefer fiscal authority
    # when money/procurement is present; otherwise prefer the spatial record.
    fiscal_priority = {"public_funding", "procurement", "contracts", "finance"}
    if domains & fiscal_priority:
        return (
            CONTRACT_REPO,
            SPIDERWEB_REPO,
            "dual_routed_contract_primary",
            "Mixed domains without explicit dual-route condition; fiscal authority priority applied.",
        )
    return (
        SPIDERWEB_REPO,
        CONTRACT_REPO,
        "dual_routed_spiderweb_primary",
        "Mixed domains without explicit dual-route condition; spatial/operational priority applied.",
    )


def _build_derivative(
    raw_item: Mapping[str, Any],
    *,
    target_repo: str,
    canonical_repo: Optional[str],
    domains: Set[str],
    final_status: str,
    output_tables: Sequence[str],
) -> Dict[str, Any]:
    source_item_id = str(raw_item.get("source_item_id") or raw_item.get("item_id") or "UNKNOWN")
    source_url = raw_item.get("source_url") or raw_item.get("url") or ""
    title = raw_item.get("title") or ""
    summary = raw_item.get("summary_own_words") or raw_item.get("summary") or raw_item.get("description") or ""

    return {
        "record_id": _stable_id(target_repo, source_item_id, source_url, title),
        "source_item_id": source_item_id,
        "target_repo": target_repo,
        "canonical_repo": canonical_repo,
        "related_repo_record_id": raw_item.get("related_repo_record_id"),
        "source_name": raw_item.get("source_name"),
        "source_url": source_url,
        "published_at": raw_item.get("published_at"),
        "discovered_at": raw_item.get("discovered_at"),
        "title": title,
        "summary_own_words": summary,
        "domains": sorted(domains),
        "final_status": final_status,
        "output_tables": sorted(set(output_tables)),
        "evidence_tier": raw_item.get("evidence_tier"),
        "confidence_level": raw_item.get("confidence_level"),
        "source_hash": raw_item.get("source_hash") or _hash_text(source_url),
        "content_hash": raw_item.get("content_hash") or _hash_text(_normalized_search_text(raw_item)),
        "dedupe_group_id": raw_item.get("dedupe_group_id"),
    }


def _validate_result(
    result: RouteResult,
    raw_item: Mapping[str, Any],
    config: RouterConfig,
    *,
    strict: bool,
) -> None:
    errors: List[str] = []

    if result.final_status not in config.final_status_values:
        errors.append(f"Invalid final_status: {result.final_status}")

    if not result.source_item_id or result.source_item_id == "UNKNOWN":
        errors.append("Missing source_item_id/item_id")

    if result.final_status.startswith("dual_routed"):
        if not result.canonical_repo or not result.derivative_repo:
            errors.append("Dual-routed result missing canonical_repo or derivative_repo")

    if result.canonical_repo == SPIDERWEB_REPO or result.derivative_repo == SPIDERWEB_REPO:
        if "every_spatial_record_has_location_or_manual_geocode_required" in config.validation_gates:
            has_location = any(
                raw_item.get(field)
                for field in (
                    "latitude",
                    "longitude",
                    "geometry",
                    "location_text",
                    "municipality_name",
                    "municipality",
                )
            ) or bool(raw_item.get("manual_geocode_required"))
            if not has_location:
                errors.append("Spatial derivative missing location fields and manual_geocode_required")

    if result.final_status in {"routed_contract_sweeper", "dual_routed_contract_primary"}:
        if raw_item.get("verification_status") == "confirmed" and not raw_item.get("matched_t1_record_url"):
            errors.append("Confirmed Contract-Sweeper item lacks matched_t1_record_url")

    result.validation_errors = errors
    if strict and errors:
        raise IntakeRouterError(f"Route validation failed for {result.source_item_id}: {errors}")


def _status_override(raw_item: Mapping[str, Any]) -> Optional[str]:
    status = str(raw_item.get("access_status") or raw_item.get("archive_status") or "").strip().lower()
    if status in INACCESSIBLE_STATUSES:
        return "source_inaccessible"
    if status in BLOCKED_STATUSES:
        return "blocked_or_paywalled"
    if status in METADATA_ONLY_STATUSES:
        return "metadata_only_archived"
    if raw_item.get("duplicate_of"):
        return "duplicate_consolidated"
    if raw_item.get("not_relevant_reason"):
        return "not_relevant_with_reason"
    return None


def _normalized_search_text(raw_item: Mapping[str, Any]) -> str:
    parts: List[str] = []
    for key in (
        "title",
        "summary",
        "summary_own_words",
        "description",
        "content",
        "text",
        "caption",
        "source_name",
        "agency_entity",
        "municipality",
        "municipality_name",
        "project_name",
        "program_name",
        "tags",
        "topic_category",
    ):
        value = raw_item.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(v) for v in value)
        else:
            parts.append(str(value))
    return _normalize_text(" ".join(parts))


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9$%./:-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _keyword_in_text(keyword: Any, normalized_text: str) -> bool:
    normalized_keyword = _normalize_text(str(keyword))
    if not normalized_keyword:
        return False
    return normalized_keyword in normalized_text


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(target_repo: str, source_item_id: str, source_url: str, title: str) -> str:
    prefix = "CS" if target_repo == CONTRACT_REPO else "SW"
    digest = _hash_text(json.dumps([target_repo, source_item_id, source_url, title], sort_keys=True))[:12]
    return f"{prefix}-PRINTAKE-{digest}"


__all__ = [
    "CONTRACT_REPO",
    "SPIDERWEB_REPO",
    "IntakeRouterError",
    "RouterConfig",
    "RouteResult",
    "classify_raw_item",
    "load_router_config",
    "route_raw_item",
    "route_raw_items",
]
