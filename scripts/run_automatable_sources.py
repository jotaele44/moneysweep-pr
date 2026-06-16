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

No secrets are printed. A run summary is written to
``data/staging/materialization_run_summary.json`` (gitignored — it carries timestamps and
row counts, so it must never be a committed/gated artifact) and echoed to stdout.

Usage:
  python3 scripts/run_automatable_sources.py --dry-run        # list the automatable set
  python3 scripts/run_automatable_sources.py                  # run all automatable (needs egress)
  python3 scripts/run_automatable_sources.py --source pr_general_fund_revenues
  python3 scripts/run_automatable_sources.py --family territorial
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.source_registry import load_source_registry
from scripts.build_source_recovery_matrix import PATH_TYPES, _classify
from scripts.check_network_egress import run_checks
from scripts.config import PROJECT_ROOT, setup_logging

ENTRYPOINTS = ("run", "main", "fetch", "download")
# Small representative set for the egress gate (fast fail; the full list lives in
# check_network_egress.DEFAULT_ENDPOINTS).
EGRESS_PROBE = ["https://api.usaspending.gov/", "https://datos.estadisticas.pr/"]
SUMMARY_REL = "data/staging/materialization_run_summary.json"


def _module_name(producer_script: str) -> str:
    name = producer_script[:-3] if producer_script.endswith(".py") else producer_script
    return name.replace("/", ".").replace("\\", ".")


def select_sources(
    sources: list[dict],
    *,
    source: str | None,
    family: str | None,
    only: list[str] | None,
) -> list[dict]:
    """Return the source dicts to run. Explicit ids bypass the automatable filter."""
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
        if PATH_TYPES[_classify(src)][0]:  # automatable
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
    except Exception as exc:  # import-time failure
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
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("run_automatable_sources")
    sources = load_source_registry(root).get("sources", [])
    selected = select_sources(sources, source=source, family=family, only=only)
    selected_ids = [s.get("source_id", "") for s in selected]

    summary: dict[str, Any] = {
        "selected_count": len(selected_ids),
        "selected": selected_ids,
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

    summary["ran"] = [run_one(root, src, logger) for src in selected]
    summary["status"] = "OK"
    summary["ok_count"] = sum(1 for r in summary["ran"] if r["status"] in ("OK", "CACHED"))
    summary["error_count"] = sum(
        1 for r in summary["ran"] if r["status"] in ("ERROR", "IMPORT_ERROR", "NO_ENTRYPOINT")
    )
    _write_summary(root, summary)
    return summary


def _write_summary(root: Path, summary: dict) -> None:
    path = root / SUMMARY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


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
