"""Run the automatable financial sources against live APIs (egress-capable runner).

This is the driver that materializes the *automatable* registry set when outbound
egress is available (a GitHub Actions runner or a local network), using API keys from
the environment / ``.env``. The buildout sandbox has no egress, so:

  - it runs an **egress preflight** (scripts.check_network_egress) first and, when egress
    is blocked, exits 0 without invoking any producer (summary marks ``egress_blocked``);
  - each producer is invoked inside try/except and its result captured — a single failing
    source never aborts the run.

Source selection reuses the recovery-matrix classifier (no reinvented logic): the default
target is every source classified ``api_adapter`` / ``api_producer``. Explicit ``--source``
/ ``--only`` override the automatable filter (run a named source regardless of class).

Desktop builds separate immutable source identity from mutable workspace state.
``MONEYSWEEP_REGISTRY_ROOT`` selects the immutable registry/classification root while
``root`` is the writable materialization workspace. The classifier must use that immutable
root as well; otherwise a frozen app can silently demote packaged producer sources merely
because the writable workspace does not contain source-code files.

Before dynamically importing any producer, the legacy ``scripts.config`` path globals are
rebound from their source-tree-relative values to equivalent paths under the workspace.
This prevents older producers that ignore a ``root=`` argument from silently writing into
packaged resources.

No secrets are printed. A latest-run summary is written to
``data/staging/materialization_run_summary.json`` and a versioned immutable-in-workspace
receipt is written under ``receipts/materialization_runs/``.

Usage:
  python3 scripts/run_automatable_sources.py --dry-run
  python3 scripts/run_automatable_sources.py
  python3 scripts/run_automatable_sources.py --source pr_general_fund_revenues
  python3 scripts/run_automatable_sources.py --family territorial
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.source_registry import load_source_registry
from scripts.build_source_recovery_matrix import PATH_TYPES, _classify
from scripts.check_network_egress import run_checks
from scripts.config import PROJECT_ROOT, setup_logging

ENTRYPOINTS = ("run", "main", "fetch", "download")
EGRESS_PROBE = ["https://api.usaspending.gov/", "https://datos.estadisticas.pr/"]
SUMMARY_REL = "data/staging/materialization_run_summary.json"
RECEIPT_DIR_REL = "receipts/materialization_runs"


def _module_name(producer_script: str) -> str:
    name = producer_script[:-3] if producer_script.endswith(".py") else producer_script
    return name.replace("/", ".").replace("\\", ".")


def _rebase_path(value: Path, old_root: Path, new_root: Path) -> Path:
    try:
        relative = value.resolve().relative_to(old_root.resolve())
    except ValueError:
        return value
    return new_root / relative


def _bind_legacy_config_to_workspace(root: Path) -> dict[str, str]:
    """Rebind scripts.config Path globals to *root* before producer imports.

    A number of older producers use module-level DATA_DIR/RAW_DIR/etc. instead
    of honoring their ``root`` argument. Rebinding every Path (and Path members
    of simple lists/tuples) that descends from the original project root keeps
    those modules workspace-safe without changing source identity or unrelated
    absolute paths.
    """
    import scripts.config as cfg

    old_root = Path(cfg.PROJECT_ROOT).resolve()
    new_root = Path(root).expanduser().resolve()
    changed: dict[str, str] = {}

    for name, value in list(vars(cfg).items()):
        if isinstance(value, Path):
            rebound = _rebase_path(value, old_root, new_root)
            if rebound != value:
                setattr(cfg, name, rebound)
                changed[name] = str(rebound)
        elif isinstance(value, list) and value and all(isinstance(item, Path) for item in value):
            rebound_list = [_rebase_path(item, old_root, new_root) for item in value]
            if rebound_list != value:
                setattr(cfg, name, rebound_list)
                changed[name] = f"{len(rebound_list)} paths"
        elif isinstance(value, tuple) and value and all(isinstance(item, Path) for item in value):
            rebound_tuple = tuple(_rebase_path(item, old_root, new_root) for item in value)
            if rebound_tuple != value:
                setattr(cfg, name, rebound_tuple)
                changed[name] = f"{len(rebound_tuple)} paths"

    cfg.PROJECT_ROOT = new_root
    changed["PROJECT_ROOT"] = str(new_root)
    return changed


def select_sources(
    sources: list[dict],
    *,
    source: str | None,
    family: str | None,
    only: list[str] | None,
    classifier_root: Path | None = None,
) -> list[dict]:
    """Return source candidates using one explicit classification root.

    ``classifier_root`` is the immutable source/resource manifestation used to
    establish producer readiness. It is intentionally distinct from the writable
    materialization workspace. Explicit ids bypass the automatable filter.
    """
    explicit = set(only or ([source] if source else []))
    selected: list[dict] = []
    for src in sources:
        sid = src.get("source_id", "")
        if explicit:
            if sid in explicit:
                selected.append(src)
            continue
        if family and src.get("family") != family:
            continue
        source_class = (
            _classify(src) if classifier_root is None else _classify(src, classifier_root)
        )
        if PATH_TYPES[source_class][0]:
            selected.append(src)
    return selected


def run_one(root: Path, src: dict, logger) -> dict:
    sid = src.get("source_id", "")
    producer = src.get("producer_script", "") or ""
    result = {"source": sid, "producer": producer, "status": "", "rows": None, "error": ""}
    if not producer:
        result["status"] = "NO_PRODUCER"
        return result
    try:
        module = importlib.import_module(_module_name(producer))
    except Exception as exc:
        result["status"] = "IMPORT_ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    fn = next((getattr(module, n) for n in ENTRYPOINTS if callable(getattr(module, n, None))), None)
    if fn is None:
        result["status"] = "NO_ENTRYPOINT"
        return result
    t0 = time.time()
    try:
        res = fn(root=root)
    except TypeError:
        try:
            res = fn()
        except Exception as exc:
            result["status"] = "ERROR"
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["seconds"] = round(time.time() - t0, 1)
    if isinstance(res, dict):
        result["rows"] = res.get("rows")
        result["status"] = res.get("status", "OK")
    else:
        result["status"] = "OK"
    logger.info(f"  [{sid}] {result['status']} rows={result['rows']}")
    return result


def run(
    root: Path | None = None,
    *,
    source: str | None = None,
    family: str | None = None,
    only: list[str] | None = None,
    dry_run: bool = False,
    require_egress: bool = True,
) -> dict:
    root = Path(root or PROJECT_ROOT).expanduser().resolve()
    logger = setup_logging("run_automatable_sources")
    registry_root = (
        Path(os.environ.get("MONEYSWEEP_REGISTRY_ROOT", str(root))).expanduser().resolve()
    )
    sources = load_source_registry(registry_root).get("sources", [])
    selected = select_sources(
        sources,
        source=source,
        family=family,
        only=only,
        classifier_root=registry_root,
    )
    selected_ids = [s.get("source_id", "") for s in selected]

    started_utc = datetime.now(timezone.utc).isoformat()
    summary: dict[str, Any] = {
        "schema_version": "1.0.0",
        "started_utc": started_utc,
        "selected_count": len(selected_ids),
        "selected": selected_ids,
        "registry_root": str(registry_root),
        "workspace_root": str(root),
        "egress_ok": None,
        "ran": [],
        "dry_run": dry_run,
    }

    if dry_run:
        logger.info(f"[dry-run] {len(selected_ids)} sources: {', '.join(selected_ids)}")
        _write_summary(root, summary)
        return summary

    if require_egress:
        egress = run_checks(EGRESS_PROBE)
        summary["egress_ok"] = egress["ok"]
        if not egress["ok"]:
            logger.warning(
                "  egress blocked — skipping producer execution (run from a networked runner)"
            )
            summary["status"] = "egress_blocked"
            _write_summary(root, summary)
            return summary

    summary["workspace_rebind"] = _bind_legacy_config_to_workspace(root)
    summary["ran"] = [run_one(root, src, logger) for src in selected]
    summary["status"] = "OK"
    summary["ok_count"] = sum(1 for r in summary["ran"] if r["status"] in ("OK", "CACHED"))
    summary["error_count"] = sum(
        1 for r in summary["ran"] if r["status"] in ("ERROR", "IMPORT_ERROR", "NO_ENTRYPOINT")
    )
    _write_summary(root, summary)
    return summary


def _write_summary(root: Path, summary: dict) -> None:
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    latest = root / SUMMARY_REL
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(payload, encoding="utf-8")

    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    receipt_dir = root / RECEIPT_DIR_REL
    receipt_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(summary.get("started_utc", "unknown")).replace(":", "-").replace("+", "_")
    receipt = receipt_dir / f"{stamp}__sha256_{digest[:16]}.json"
    if not receipt.exists():
        receipt.write_text(payload, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None, help="Run a single source id (any class).")
    parser.add_argument("--family", default=None, help="Limit automatable selection to a family.")
    parser.add_argument("--only", default=None, help="Comma-separated source ids (any class).")
    parser.add_argument("--dry-run", action="store_true", help="List the selection; run nothing.")
    parser.add_argument(
        "--no-require-egress",
        action="store_true",
        help="Run producers even if the egress preflight fails.",
    )
    args = parser.parse_args(argv)
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    result = run(
        source=args.source,
        family=args.family,
        only=only,
        dry_run=args.dry_run,
        require_egress=not args.no_require_egress,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "ran"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
