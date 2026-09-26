from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.download_cabilderos import REGISTRY_URL as CABILDEROS_URL
from scripts.download_cabilderos import run as run_cabilderos
from scripts.download_prasa_contracts import SOURCE_URL as PRASA_URL
from scripts.download_prasa_contracts import run as run_prasa
from tools.operator_corpus_common import expected_outputs, load_sources
from tools.write_operator_evidence_receipt import build_receipt

SCHEMA_VERSION = "moneysweep.certification_public_adapters/v1"

Adapter = tuple[str, str, Callable[..., dict[str, Any]]]

ADAPTERS: dict[str, Adapter] = {
    "pr_cabilderos": (
        "scripts/download_cabilderos.py",
        CABILDEROS_URL,
        run_cabilderos,
    ),
    "prasa": (
        "scripts/download_prasa_contracts.py",
        PRASA_URL,
        run_prasa,
    ),
}


def _present_outputs(workspace: Path, source: dict[str, Any]) -> list[str]:
    present: list[str] = []
    for expected in expected_outputs(source):
        path = workspace / expected
        if expected.endswith("/"):
            if path.is_dir():
                present.extend(
                    item.relative_to(workspace).as_posix()
                    for item in sorted(path.rglob("*"))
                    if item.is_file()
                )
        elif path.is_file():
            present.append(Path(expected).as_posix())
    return sorted(set(present))


def execute(
    *,
    registry_root: Path,
    workspace: Path,
    receipts_dir: Path,
    producer_sha: str,
) -> dict[str, Any]:
    registry_root = registry_root.resolve()
    workspace = workspace.resolve()
    receipts_dir = receipts_dir.resolve()
    receipts_dir.mkdir(parents=True, exist_ok=True)

    sources, _ = load_sources(registry_root)
    source_by_id = {str(source["source_id"]): source for source in sources}

    results: list[dict[str, Any]] = []
    for source_id in sorted(ADAPTERS):
        producer, source_url, runner = ADAPTERS[source_id]
        source = source_by_id.get(source_id)
        if source is None:
            results.append(
                {
                    "source_id": source_id,
                    "state": "SOURCE_NOT_REGISTERED",
                    "producer": producer,
                }
            )
            continue

        try:
            runner_result = runner(root=workspace, force=True)
        except Exception as exc:  # noqa: BLE001 - preserve exact acquisition blocker
            runner_result = {
                "status": "error",
                "error": f"{type(exc).__name__}:{exc}",
            }

        outputs = _present_outputs(workspace, source)
        receipt_path = None
        receipt_error = None
        if outputs:
            try:
                receipt = build_receipt(
                    root=workspace,
                    registry_root=registry_root,
                    source_id=source_id,
                    outputs=outputs,
                    producer_sha=producer_sha,
                    producer=producer,
                    source_url=source_url,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    coverage_contract_pass=False,
                )
            except Exception as exc:  # noqa: BLE001 - report, never promote silently
                receipt_error = f"{type(exc).__name__}:{exc}"
            else:
                receipt_path = receipts_dir / f"{source_id}.json"
                receipt_path.write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

        runner_status = str(runner_result.get("status") or "").lower()
        positive_runner = runner_status in {"complete", "ok", "cached"}
        if receipt_path is not None and positive_runner:
            state = "PUBLIC_ADAPTER_RECEIPTED"
        elif receipt_path is not None:
            state = "PUBLIC_ADAPTER_OUTPUT_RECEIPTED_WITH_RUNNER_BLOCKER"
        elif outputs:
            state = "PUBLIC_ADAPTER_RECEIPT_FAILED"
        else:
            state = "PUBLIC_ADAPTER_NO_OUTPUT"

        results.append(
            {
                "source_id": source_id,
                "state": state,
                "producer": producer,
                "source_url": source_url,
                "runner_result": runner_result,
                "outputs": outputs,
                "receipt_path": (
                    receipt_path.as_posix() if receipt_path is not None else None
                ),
                "receipt_error": receipt_error,
            }
        )

    counts: dict[str, int] = {}
    for result in results:
        state = str(result["state"])
        counts[state] = counts.get(state, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "workspace": str(workspace),
        "state_counts": dict(sorted(counts.items())),
        "sources": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run bounded public certification adapters inside the assembled "
            "operator workspace."
        )
    )
    parser.add_argument("--registry-root", type=Path, default=Path("."))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--producer-sha", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/certification_public_adapters.json"),
    )
    args = parser.parse_args()

    report = execute(
        registry_root=args.registry_root,
        workspace=args.workspace,
        receipts_dir=args.receipts_dir,
        producer_sha=args.producer_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"state_counts": report["state_counts"]},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
