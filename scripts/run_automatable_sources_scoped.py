"""Run automatable sources with source-scoped provider credentials.

This wrapper preserves the existing materializer selection, egress gate, result
aggregation, and summary contract while preventing dynamically imported producer
modules from seeing unrelated provider API credentials.

Credential ownership is derived from the canonical source registry. Sources whose
``authentication`` value is ``api_key:NAME`` may see only ``NAME`` during their
import and execution. Keyless sources see none of the registry-declared provider
keys. Any source declaring ``license_gate`` is fail-closed unless the named gate
environment variable is explicitly truthy.

No credential values are printed or written to the materialization summary.

Invoke from the repository root with
``python -m scripts.run_automatable_sources_scoped`` so first-party packages
resolve identically in clean checkouts and CI.
"""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from moneysweep.runtime.source_registry import load_source_registry
from scripts import run_automatable_sources as base
from scripts.build_source_recovery_matrix import PATH_TYPES, _classify
from scripts.config import PROJECT_ROOT, setup_logging

_TRUTHY = {"1", "true", "yes", "on"}
_API_KEY_PREFIX = "api_key:"


def _declared_api_key(src: dict) -> str | None:
    auth = str(src.get("authentication") or "").strip()
    if not auth.startswith(_API_KEY_PREFIX):
        return None
    key = auth[len(_API_KEY_PREFIX) :].strip()
    return key or None


def _credential_names(sources: list[dict]) -> set[str]:
    return {key for src in sources if (key := _declared_api_key(src))}


def _license_allowed(src: dict) -> bool:
    gate = str(src.get("license_gate") or "").strip()
    if not gate:
        return True
    return os.environ.get(gate, "").strip().lower() in _TRUTHY


@contextmanager
def _source_scoped_environment(
    all_credential_names: set[str],
    allowed_credential_name: str | None,
) -> Iterator[None]:
    """Temporarily hide all unrelated registry-declared provider credentials."""
    saved = {name: os.environ[name] for name in all_credential_names if name in os.environ}
    try:
        for name in all_credential_names:
            if name != allowed_credential_name:
                os.environ.pop(name, None)
        yield
    finally:
        for name in all_credential_names:
            os.environ.pop(name, None)
        os.environ.update(saved)


def _select_sources(
    sources: list[dict],
    *,
    source: str | None,
    family: str | None,
    only: list[str] | None,
) -> list[dict]:
    """Mirror the canonical selector so this wrapper remains behavior-compatible."""
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
        if PATH_TYPES[_classify(src)][0]:
            selected.append(src)
    return selected


def _blocked_result(src: dict, status: str) -> dict:
    return {
        "source": src.get("source_id", ""),
        "producer": src.get("producer_script", "") or "",
        "status": status,
        "rows": None,
        "error": "",
    }


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
    logger = setup_logging("run_automatable_sources_scoped")
    sources = load_source_registry(root).get("sources", [])
    selected = _select_sources(sources, source=source, family=family, only=only)
    selected_ids = [s.get("source_id", "") for s in selected]
    credential_names = _credential_names(sources)

    summary = {
        "selected_count": len(selected_ids),
        "selected": selected_ids,
        "egress_ok": None,
        "ran": [],
        "dry_run": dry_run,
        "credential_scope": "source_registry",
    }

    if dry_run:
        logger.info(f"[dry-run] {len(selected_ids)} sources: {', '.join(selected_ids)}")
        base._write_summary(root, summary)
        return summary

    if require_egress:
        egress = base.run_checks(base.EGRESS_PROBE)
        summary["egress_ok"] = egress["ok"]
        if not egress["ok"]:
            logger.warning(
                "  egress blocked — skipping producer execution (run from a networked runner)"
            )
            summary["status"] = "egress_blocked"
            base._write_summary(root, summary)
            return summary

    ran: list[dict] = []
    for src in selected:
        sid = src.get("source_id", "")
        allowed_key = _declared_api_key(src)

        if not _license_allowed(src):
            logger.info(f"  [{sid}] LICENSE_GATE_BLOCKED")
            ran.append(_blocked_result(src, "LICENSE_GATE_BLOCKED"))
            continue

        with _source_scoped_environment(credential_names, allowed_key):
            ran.append(base.run_one(root, src, logger))

    summary["ran"] = ran
    summary["status"] = "OK"
    summary["ok_count"] = sum(1 for r in ran if r["status"] in ("OK", "CACHED"))
    summary["error_count"] = sum(
        1 for r in ran if r["status"] in ("ERROR", "IMPORT_ERROR", "NO_ENTRYPOINT")
    )
    summary["license_blocked_count"] = sum(1 for r in ran if r["status"] == "LICENSE_GATE_BLOCKED")
    base._write_summary(root, summary)
    return summary


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
