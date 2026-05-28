#!/usr/bin/env python3
"""CLI wrapper for the shared Puerto Rico intake router.

Reads raw intake items from JSONL, JSON array, or CSV; routes them through
``shared.pr_intake_router``; and exports repo-specific derivative CSVs plus a
full route-results audit log.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

# Allow direct execution from repo root or scripts/.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.pr_intake_router import (  # noqa: E402
    CONTRACT_REPO,
    SPIDERWEB_REPO,
    IntakeRouterError,
    load_router_config,
    route_raw_item,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route Puerto Rico raw intake items into repo-specific derivative outputs.")
    parser.add_argument("--input", required=True, help="Input JSONL, JSON array, or CSV file containing raw intake items.")
    parser.add_argument("--config", default="config/pr_intake_domain_router.yaml", help="Router YAML config path.")
    parser.add_argument("--out-dir", default="data/exports/pr_intake_router", help="Directory for exported route outputs.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail immediately on the first validation error. Without this flag, records are preserved and errors go to review output.",
    )
    parser.add_argument(
        "--fail-on-validation-errors",
        action="store_true",
        help="Write outputs, then return exit code 2 if any route result has validation errors.",
    )
    return parser.parse_args(argv)


def load_items(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        items: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                item = json.loads(stripped)
                if not isinstance(item, dict):
                    raise ValueError(f"JSONL line {line_number} is not an object")
                items.append(item)
        return items

    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "items" in data:
            data = data["items"]
        if not isinstance(data, list):
            raise ValueError("JSON input must be an array or an object with an 'items' array")
        if not all(isinstance(row, dict) for row in data):
            raise ValueError("JSON input array must contain only objects")
        return list(data)

    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    raise ValueError(f"Unsupported input format: {path.suffix}. Use .jsonl, .json, or .csv")


def flatten_for_csv(row: Mapping[str, Any]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (dict, list, tuple, set)):
            flat[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        elif value is None:
            flat[key] = ""
        else:
            flat[key] = value
    return flat


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: List[Mapping[str, Any]]) -> None:
    flat_rows = [flatten_for_csv(row) for row in rows]
    fieldnames = sorted({key for row in flat_rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_rows)


def main_with_args(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    config_path = Path(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = load_router_config(config_path)
    raw_items = load_items(input_path)

    results = []
    contract_rows: List[Mapping[str, Any]] = []
    spiderweb_rows: List[Mapping[str, Any]] = []
    review_rows: List[Mapping[str, Any]] = []

    for item in raw_items:
        try:
            result = route_raw_item(item, config, strict=args.strict)
        except IntakeRouterError as exc:
            if args.strict:
                raise
            result = route_raw_item(item, config, strict=False)
            result.validation_errors.append(str(exc))

        result_dict = result.to_dict()
        results.append(result_dict)

        if result.contract_sweeper_derivative:
            contract_rows.append(result.contract_sweeper_derivative)
        if result.spiderweb_pr_derivative:
            spiderweb_rows.append(result.spiderweb_pr_derivative)
        if result.validation_errors or result.final_status in {
            "manual_review_required",
            "source_inaccessible",
            "blocked_or_paywalled",
            "metadata_only_archived",
            "not_relevant_with_reason",
        }:
            review_rows.append(
                {
                    "source_item_id": result.source_item_id,
                    "final_status": result.final_status,
                    "canonical_repo": result.canonical_repo,
                    "derivative_repo": result.derivative_repo,
                    "review_reason": result.review_reason,
                    "validation_errors": result.validation_errors,
                }
            )

    status_counts: Dict[str, int] = {}
    for result in results:
        status = str(result.get("final_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1

    summary = {
        "input_path": str(input_path),
        "config_path": str(config_path),
        "raw_item_count": len(raw_items),
        "route_result_count": len(results),
        "contract_sweeper_derivative_count": len(contract_rows),
        "spiderweb_pr_derivative_count": len(spiderweb_rows),
        "review_queue_count": len(review_rows),
        "status_counts": status_counts,
        "zero_loss_pass": len(raw_items) == len(results) and all(row.get("final_status") for row in results),
        "validation_error_count": sum(1 for row in results if row.get("validation_errors")),
    }

    write_jsonl(out_dir / "route_results.jsonl", results)
    write_csv(out_dir / "contract_sweeper_derivatives.csv", contract_rows)
    write_csv(out_dir / "spiderweb_pr_derivatives.csv", spiderweb_rows)
    write_csv(out_dir / "manual_review_queue.csv", review_rows)
    (out_dir / "routing_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    if not summary["zero_loss_pass"]:
        print(json.dumps(summary, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1
    if args.fail_on_validation_errors and summary["validation_error_count"]:
        print(json.dumps(summary, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    return main_with_args()


if __name__ == "__main__":
    raise SystemExit(main())
