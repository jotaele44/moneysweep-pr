"""Pipeline readiness preflight.

Inspects every source declared in the registry — producer path, importability,
callable entrypoint, and API-key presence — WITHOUT executing any producer or
making network calls. Informational by default; under strict mode the caller
aborts the pipeline when structural errors are present.

Public API:
    run_pipeline_preflight(root, logger, strict=False, write_report=False) -> dict
    classify_source_readiness(root, source) -> dict
"""

from __future__ import annotations

import importlib
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ENTRYPOINT_NAMES = ("run", "main", "fetch", "download")

# Readiness statuses that represent a real, fixable structural defect.
STRUCTURAL_STATUSES = frozenset(
    {"blocked_required_archived", "missing_producer", "import_error", "missing_callable"}
)


def _ensure_on_path(root: Path) -> None:
    """Make `root` importable so producer/registry modules resolve."""
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _load_dotenv_dict(root: Path) -> dict:
    """Return parsed `.env` as a dict. `_load_dotenv` does not mutate os.environ."""
    try:
        from scripts.config import _load_dotenv

        return _load_dotenv(root / ".env")
    except Exception:
        return {}


def _api_key_present(env_var: str, dotenv: dict) -> bool:
    """True if the key is set via environment or `.env`. Never returns the value."""
    if os.environ.get(env_var, "").strip():
        return True
    return bool(str(dotenv.get(env_var, "")).strip())


def _producer_module_name(producer_script: str) -> str:
    """Map `scripts/download_fec.py` -> `scripts.download_fec`."""
    name = producer_script[:-3] if producer_script.endswith(".py") else producer_script
    return name.replace("/", ".").replace("\\", ".")


def classify_source_readiness(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    """Classify a single registry source's readiness — no execution, no network.

    Statuses: ready, missing_key_limited, archived_optional,
    blocked_required_archived, missing_producer, import_error, missing_callable.
    (`report_drift` is part of the vocabulary but reserved — not assigned here,
    as there is no cheap, false-positive-free signal for it.)
    """
    _ensure_on_path(root)
    sid = source.get("source_id") or "<unknown>"
    producer = source.get("producer_script") or ""
    required = bool(source.get("required"))
    auth = source.get("authentication") or ""
    issues: list[str] = []

    result: dict[str, Any] = {
        "source_id": sid,
        "family": source.get("family", ""),
        "required": required,
        "authentication": auth,
        "producer_script": producer,
        "expected_outputs": list(source.get("expected_outputs") or []),
        "entrypoint": None,
        "readiness_status": "ready",
        "issues": issues,
    }

    # Archived producers are classified by path + required flag — never imported.
    if producer.startswith("archive/"):
        if required:
            result["readiness_status"] = "blocked_required_archived"
            issues.append("required source has an archived producer_script")
        else:
            result["readiness_status"] = "archived_optional"
        return result

    if not producer:
        result["readiness_status"] = "missing_producer"
        issues.append("no producer_script declared in registry")
        return result

    if not (root / producer).exists():
        result["readiness_status"] = "missing_producer"
        issues.append(f"producer_script not found on disk: {producer}")
        return result

    module_name = _producer_module_name(producer)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # ImportError or any import-time failure
        result["readiness_status"] = "import_error"
        issues.append(f"import of {module_name} failed: {type(exc).__name__}: {exc}")
        return result

    entrypoint = next((n for n in ENTRYPOINT_NAMES if callable(getattr(module, n, None))), None)
    if entrypoint is None:
        result["readiness_status"] = "missing_callable"
        issues.append("no callable entrypoint found (" + "/".join(ENTRYPOINT_NAMES) + ")")
        return result
    result["entrypoint"] = entrypoint

    # API-key-gated producer: importable + callable but key absent -> limited, not broken.
    if auth.startswith("api_key:"):
        env_var = auth.split(":", 1)[1]
        if not _api_key_present(env_var, _load_dotenv_dict(root)):
            result["readiness_status"] = "missing_key_limited"
            issues.append(f"{env_var} not set — source will be skipped/limited")

    return result


def _write_preflight_report(root: Path, result: dict[str, Any], logger) -> None:
    """Merge a `pipeline_preflight` summary block into reports/current_status.json."""
    import json

    path = root / "reports" / "current_status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"  [preflight] could not update {path.name}: {exc}")
        return
    data["pipeline_preflight"] = {
        "run_at": date.today().isoformat(),
        "total_sources": result["total_sources"],
        "status_counts": result["status_counts"],
        "structural_errors": result["structural_errors"],
        "missing_keys": [m["source_id"] for m in result["missing_keys"]],
        "strict": result["strict"],
        "ok": result["ok"],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    logger.info(f"  [preflight] wrote summary to {path.name}")


def run_pipeline_preflight(
    root: Path,
    logger,
    strict: bool = False,
    write_report: bool = False,
) -> dict[str, Any]:
    """Classify every registry source's readiness and log a summary.

    No producers are executed and no network calls are made. Missing API keys are
    never structural errors. `ok` is False only when the registry cannot load at
    all (any mode) or — under strict mode — when structural errors are present.
    """
    _ensure_on_path(root)
    logger.info("-" * 70)
    logger.info(f"  Pipeline readiness preflight (strict={strict})")
    logger.info("-" * 70)

    try:
        from moneysweep.runtime.source_registry import all_sources

        sources = all_sources(root)
    except Exception as exc:
        logger.error(f"  [preflight] registry could not be loaded: {exc}")
        logger.info("-" * 70)
        logger.info("")
        return {
            "total_sources": 0,
            "checked_sources": 0,
            "status_counts": {},
            "missing_keys": [],
            "structural_errors": [],
            "strict": strict,
            "ok": False,
            "details": [],
        }

    dotenv = _load_dotenv_dict(root)

    # --- API-key status pass: covers every api_key source, never logs values ---
    missing_keys: list[dict[str, str]] = []
    for src in sources:
        auth = src.get("authentication") or ""
        if not auth.startswith("api_key:"):
            continue
        sid = src.get("source_id") or "<unknown>"
        env_var = auth.split(":", 1)[1]
        if _api_key_present(env_var, dotenv):
            logger.info(f"  [OK]      {sid} ({env_var})")
        else:
            logger.warning(f"  [MISSING] {sid} ({env_var}) — source will be skipped/limited")
            missing_keys.append({"source_id": sid, "env_var": env_var})

    # --- Per-source readiness classification ---
    details = [classify_source_readiness(root, src) for src in sources]
    status_counts = dict(Counter(d["readiness_status"] for d in details))
    structural_errors = [
        d["source_id"] for d in details if d["readiness_status"] in STRUCTURAL_STATUSES
    ]

    # Every source logged at DEBUG; problems/limited surfaced at INFO/ERROR.
    for d in details:
        line = f"  [{d['readiness_status']}] {d['source_id']}"
        if d["issues"]:
            line += " — " + "; ".join(d["issues"])
        if d["readiness_status"] in STRUCTURAL_STATUSES:
            logger.error(line)
        elif d["readiness_status"] == "missing_key_limited":
            logger.warning(line)
        else:
            logger.debug(line)

    logger.info("  Readiness: " + ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items())))
    logger.info(
        f"  {len(sources)} sources checked — "
        f"{len(structural_errors)} structural error(s), "
        f"{len(missing_keys)} missing key(s)."
    )

    ok = (not structural_errors) if strict else True

    if structural_errors:
        joined = ", ".join(structural_errors)
        if strict:
            logger.error(f"  [preflight] strict mode: structural errors → {joined}")
        else:
            logger.warning(
                f"  [preflight] structural errors present (non-fatal in non-strict mode): {joined}"
            )
    if missing_keys:
        logger.info("  [preflight] missing API keys are non-fatal — sources skip or run limited.")

    logger.info("-" * 70)
    logger.info("")

    result = {
        "total_sources": len(sources),
        "checked_sources": len(details),
        "status_counts": status_counts,
        "missing_keys": missing_keys,
        "structural_errors": structural_errors,
        "strict": strict,
        "ok": ok,
        "details": details,
    }

    if write_report:
        _write_preflight_report(root, result, logger)

    return result
