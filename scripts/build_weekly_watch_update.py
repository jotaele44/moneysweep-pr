#!/usr/bin/env python3
"""Build the weekly watch update plan from registry/watch_sources.json.

This script is intentionally network-free. It turns the watch registry into a
reviewable operator plan and machine-readable queue. Live fetchers can be added
source-by-source later without changing the promotion controls introduced here.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "registry" / "watch_sources.json"
DEFAULT_OUT_JSON = ROOT / "reports" / "weekly_watch_update_plan.json"
DEFAULT_OUT_MD = ROOT / "reports" / "weekly_watch_update_plan.md"

REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "display_name",
    "organization",
    "category",
    "jurisdiction",
    "url",
    "cadence",
    "evidence_tier",
    "data_mode",
    "promotion_eligible",
    "watch_keywords",
    "corroboration_targets",
}

INFORMATIVE_CATEGORIES = {
    "official_social_informative",
    "media_signal",
}


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("watch registry must be a JSON object")
    if not isinstance(data.get("watch_sources"), list):
        raise ValueError("watch registry must contain watch_sources list")
    return data


def validate_source(source: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_SOURCE_FIELDS - set(source))
    if missing:
        errors.append(f"{source.get('source_id', '<unknown>')}: missing fields {missing}")

    source_id = source.get("source_id", "<unknown>")
    if source.get("category") in INFORMATIVE_CATEGORIES:
        if source.get("promotion_eligible") is not False:
            errors.append(f"{source_id}: informative/social source must not be promotion eligible")
        if source.get("data_mode") != "informative_only":
            errors.append(f"{source_id}: informative/social source must use data_mode=informative_only")

    if source.get("category") == "official_social_informative" and source.get("evidence_tier") != "T4":
        errors.append(f"{source_id}: official social source must use evidence_tier=T4")

    if source.get("promotion_eligible") is True and source.get("evidence_tier") == "T4":
        errors.append(f"{source_id}: T4 source cannot be promotion eligible")

    if not isinstance(source.get("watch_keywords", []), list) or not source.get("watch_keywords"):
        errors.append(f"{source_id}: watch_keywords must be a non-empty list")

    if not isinstance(source.get("corroboration_targets", []), list):
        errors.append(f"{source_id}: corroboration_targets must be a list")

    return errors


def build_plan(registry: dict[str, Any]) -> dict[str, Any]:
    sources = registry["watch_sources"]
    validation_errors: list[str] = []
    for source in sources:
        validation_errors.extend(validate_source(source))

    categories = Counter(source["category"] for source in sources)
    evidence_tiers = Counter(source["evidence_tier"] for source in sources)
    data_modes = Counter(source["data_mode"] for source in sources)

    queue_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sorted(sources, key=lambda s: (s["category"], s["source_id"])):
        queue_by_category[source["category"]].append(
            {
                "source_id": source["source_id"],
                "display_name": source["display_name"],
                "url": source["url"],
                "cadence": source["cadence"],
                "evidence_tier": source["evidence_tier"],
                "data_mode": source["data_mode"],
                "promotion_eligible": source["promotion_eligible"],
                "watch_keywords": source["watch_keywords"],
                "corroboration_targets": source["corroboration_targets"],
            }
        )

    informative_only = [
        source["source_id"]
        for source in sources
        if source["data_mode"] == "informative_only" or source["category"] in INFORMATIVE_CATEGORIES
    ]

    promotion_eligible = [source["source_id"] for source in sources if source["promotion_eligible"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": registry.get("schema_version", "1.0"),
        "producer": registry.get("producer", "moneysweep-pr"),
        "source_count": len(sources),
        "category_counts": dict(sorted(categories.items())),
        "evidence_tier_counts": dict(sorted(evidence_tiers.items())),
        "data_mode_counts": dict(sorted(data_modes.items())),
        "promotion_eligible_count": len(promotion_eligible),
        "promotion_eligible_sources": sorted(promotion_eligible),
        "informative_only_count": len(informative_only),
        "informative_only_sources": sorted(informative_only),
        "validation_errors": validation_errors,
        "weekly_queue": dict(sorted(queue_by_category.items())),
        "operator_rule": "Social/media sources generate leads only. Promotion requires corroborating authoritative records and review-state approval.",
    }


def render_markdown(plan: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Weekly Watch Update Plan")
    lines.append("")
    lines.append(f"Generated: `{plan['generated_at']}`")
    lines.append(f"Producer: `{plan['producer']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Sources | {plan['source_count']} |")
    lines.append(f"| Promotion eligible | {plan['promotion_eligible_count']} |")
    lines.append(f"| Informative only | {plan['informative_only_count']} |")
    lines.append(f"| Validation errors | {len(plan['validation_errors'])} |")
    lines.append("")
    lines.append("## Category counts")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|---|---:|")
    for category, count in plan["category_counts"].items():
        lines.append(f"| `{category}` | {count} |")
    lines.append("")
    lines.append("## Weekly queue")
    lines.append("")
    for category, rows in plan["weekly_queue"].items():
        lines.append(f"### `{category}`")
        lines.append("")
        lines.append("| Source | Tier | Mode | Promotion | Corroboration targets |")
        lines.append("|---|---|---|---:|---|")
        for row in rows:
            targets = ", ".join(f"`{target}`" for target in row["corroboration_targets"])
            lines.append(
                f"| `{row['source_id']}` | `{row['evidence_tier']}` | "
                f"`{row['data_mode']}` | {str(row['promotion_eligible']).lower()} | {targets} |"
            )
        lines.append("")
    lines.append("## Operator rule")
    lines.append("")
    lines.append(plan["operator_rule"])
    lines.append("")
    if plan["validation_errors"]:
        lines.append("## Validation errors")
        lines.append("")
        for error in plan["validation_errors"]:
            lines.append(f"- {error}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when registry validation fails")
    args = parser.parse_args()

    registry = load_registry(args.registry)
    plan = build_plan(registry)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_md.write_text(render_markdown(plan), encoding="utf-8")

    if args.strict and plan["validation_errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
