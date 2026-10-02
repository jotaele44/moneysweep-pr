#!/usr/bin/env python3
"""Enforce end-to-end GUI capability parity with a no-new-debt ratchet.

The manifest is the human-reviewed capability contract. Discovery is deliberately
broad: it inventories production/analysis Python modules and public symbols,
HTTP endpoints, GUI pages/routes/controls, client API functions, CLI-only
surfaces, dead controls, placeholder/mock markers, and routes that are not
discoverable outside the route table.

Existing findings live in a committed baseline. Pull requests may reduce that
baseline, but any newly discovered unpaired signal fails. Active manifest
capabilities are validated bidirectionally and must carry an end-to-end GUI test.
The script is dependency-free and supports Python 3.9+.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# fmt: off

MANIFEST_SCHEMA = "prii.gui-capability/v1"
BASELINE_SCHEMA = "prii.gui-parity-baseline/v1"
REPORT_SCHEMA = "prii.gui-parity-report/v1"

CLASSIFICATIONS = {"user", "operator", "analysis", "client_only", "internal"}
STATUSES = {"active", "staged", "legacy"}
HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
FRONTEND_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

ENDPOINT_RE = re.compile(
    r"@\s*[A-Za-z_][A-Za-z0-9_]*\s*\.\s*"
    r"(get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
ROUTE_RES = (
    re.compile(r"<Route\b[^>]*\bpath\s*=\s*[\"']([^\"']+)[\"']", re.DOTALL),
    re.compile(r"\bpath\s*:\s*[\"']([^\"']+)[\"']"),
)
CONTROL_RE = re.compile(
    r"<(button|form|input|select|textarea)\b[^>]*>", re.IGNORECASE | re.DOTALL
)
JS_FUNCTION_RES = (
    re.compile(
        r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    ),
    re.compile(
        r"\bexport\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="
    ),
)
PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|FIXME|mock(?:ed|ing)?|fake|seedData|not implemented|"
    r"coming soon|should be added later)\b",
    re.IGNORECASE,
)
CLI_RE = re.compile(
    r"(?:\bargparse\b|\bTyper\s*\(|@click\.|\.add_parser\s*\(|"
    r"@(?:app|cli)\.command\s*\()"
)

DEFAULT_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "archive",
    "vendor",
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_id(kind: str, *parts: str) -> str:
    escaped = [part.replace("\\", "/").strip() for part in parts]
    return ":".join([kind, *escaped])


def _candidate(
    kind: str,
    path: str,
    *,
    detail: str = "",
    symbol: str = "",
    line: int | None = None,
) -> dict[str, Any]:
    identity = [path]
    if symbol:
        identity.append(symbol)
    if detail:
        identity.append(detail)
    if line is not None and not detail and not symbol:
        identity.append(str(line))
    return {
        "id": _candidate_id(kind, *identity),
        "kind": kind,
        "path": path,
        **({"detail": detail} if detail else {}),
        **({"symbol": symbol} if symbol else {}),
        **({"line": line} if line is not None else {}),
        "signal": signal_for_kind(kind),
    }


def signal_for_kind(kind: str) -> str:
    if kind.startswith("analysis_"):
        return "ANALYSIS_NOT_GUI_RENDERED"
    if kind == "cli_surface":
        return "TERMINAL_REQUIRED"
    if kind == "dead_control":
        return "DEAD_CONTROL"
    if kind == "mock_marker":
        return "PRODUCTION_PLACEHOLDER_OR_MOCK"
    if kind == "gui_unreachable":
        return "GUI_WORKFLOW_UNREACHABLE"
    if kind.startswith("gui_") or kind in {"frontend_api_client"}:
        return "GUI_NOT_BACKEND_WIRED"
    return "BACKEND_NOT_GUI_SURFACED"


def _matches_exclude(rel: str, patterns: Iterable[str]) -> bool:
    parts = set(Path(rel).parts)
    if parts & DEFAULT_EXCLUDED_PARTS:
        return True
    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def _iter_files(
    repo_root: Path,
    roots: Iterable[str],
    suffixes: set[str],
    excludes: Iterable[str],
) -> list[Path]:
    found: set[Path] = set()
    for configured in roots:
        candidate = (repo_root / configured).resolve()
        try:
            candidate.relative_to(repo_root.resolve())
        except ValueError:
            continue
        paths = [candidate] if candidate.is_file() else candidate.rglob("*") if candidate.exists() else []
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            rel = path.relative_to(repo_root).as_posix()
            if not _matches_exclude(rel, excludes):
                found.add(path)
    return sorted(found)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _discover_python(
    repo_root: Path,
    discovery: dict[str, Any],
) -> list[dict[str, Any]]:
    excludes = discovery.get("exclude", [])
    backend_roots = list(discovery.get("backend_roots", []))
    analysis_roots = list(discovery.get("analysis_roots", []))
    production_roots = list(discovery.get("production_roots", []))

    backend_files = set(_iter_files(repo_root, backend_roots, {".py"}, excludes))
    analysis_files = set(_iter_files(repo_root, analysis_roots, {".py"}, excludes))
    production_files = set(
        _iter_files(
            repo_root,
            [*production_roots, *backend_roots, *analysis_roots],
            {".py"},
            excludes,
        )
    )

    records: list[dict[str, Any]] = []
    for path in sorted(production_files):
        rel = path.relative_to(repo_root).as_posix()
        text = _read_text(path)
        is_analysis = path in analysis_files and path not in backend_files
        module_kind = "analysis_module" if is_analysis else "python_module"
        symbol_kind = "analysis_symbol" if is_analysis else "python_symbol"
        records.append(_candidate(module_kind, rel))

        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in tree.body:
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    continue
                if node.name.startswith("_"):
                    continue
                records.append(
                    _candidate(
                        symbol_kind,
                        rel,
                        symbol=node.name,
                        line=getattr(node, "lineno", None),
                    )
                )

        if CLI_RE.search(text):
            records.append(_candidate("cli_surface", rel))

        if path in backend_files:
            for match in ENDPOINT_RE.finditer(text):
                detail = f"{match.group(1).upper()} {match.group(2)}"
                records.append(
                    _candidate(
                        "backend_endpoint",
                        rel,
                        detail=detail,
                        line=text.count("\n", 0, match.start()) + 1,
                    )
                )
    return records


def _discover_frontend(
    repo_root: Path,
    discovery: dict[str, Any],
) -> list[dict[str, Any]]:
    excludes = discovery.get("exclude", [])
    frontend_roots = list(discovery.get("frontend_roots", []))
    page_roots = list(
        discovery.get("frontend_capability_roots", frontend_roots)
    )
    api_roots = list(discovery.get("frontend_api_roots", []))
    route_files = {
        (repo_root / value).resolve() for value in discovery.get("route_files", [])
    }

    frontend_files = _iter_files(
        repo_root, frontend_roots, FRONTEND_SUFFIXES, excludes
    )
    page_files = set(
        _iter_files(repo_root, page_roots, {".jsx", ".tsx"}, excludes)
    )
    api_files = set(
        _iter_files(repo_root, api_roots, FRONTEND_SUFFIXES, excludes)
    )

    records: list[dict[str, Any]] = []
    route_records: list[dict[str, Any]] = []
    all_frontend_text: dict[Path, str] = {}

    for path in frontend_files:
        rel = path.relative_to(repo_root).as_posix()
        text = _read_text(path)
        all_frontend_text[path.resolve()] = text

        if path in page_files:
            records.append(_candidate("gui_page", rel))

        if path in api_files:
            for pattern in JS_FUNCTION_RES:
                for match in pattern.finditer(text):
                    records.append(
                        _candidate(
                            "frontend_api_client",
                            rel,
                            symbol=match.group(1),
                            line=text.count("\n", 0, match.start()) + 1,
                        )
                    )

        for match in CONTROL_RE.finditer(text):
            tag = match.group(1).lower()
            normalized = re.sub(r"\s+", " ", match.group(0)).strip()
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
            detail = f"{tag}#{digest}"
            records.append(
                _candidate(
                    "gui_control",
                    rel,
                    detail=detail,
                    line=text.count("\n", 0, match.start()) + 1,
                )
            )
            if tag == "button":
                has_handler = re.search(r"\bon[A-Z]\w*\s*=", match.group(0))
                is_submit = re.search(
                    r"\btype\s*=\s*[\"']submit[\"']", match.group(0), re.IGNORECASE
                )
                if not has_handler and not is_submit:
                    records.append(
                        _candidate(
                            "dead_control",
                            rel,
                            detail=detail,
                            line=text.count("\n", 0, match.start()) + 1,
                        )
                    )

        for line_number, line in enumerate(text.splitlines(), start=1):
            marker = PLACEHOLDER_RE.search(line)
            if not marker:
                continue
            snippet = re.sub(r"\s+", " ", line.strip())
            digest = hashlib.sha1(snippet.encode("utf-8")).hexdigest()[:12]
            records.append(
                _candidate(
                    "mock_marker",
                    rel,
                    detail=f"{marker.group(0).lower()}#{digest}",
                    line=line_number,
                )
            )

    for route_file in sorted(route_files):
        if not route_file.exists():
            continue
        rel = route_file.relative_to(repo_root).as_posix()
        text = all_frontend_text.get(route_file, _read_text(route_file))
        for pattern in ROUTE_RES:
            for match in pattern.finditer(text):
                route = match.group(1)
                record = _candidate(
                    "gui_route",
                    rel,
                    detail=route,
                    line=text.count("\n", 0, match.start()) + 1,
                )
                records.append(record)
                route_records.append(record)

    for implicit in discovery.get("implicit_routes", []):
        if not isinstance(implicit, dict):
            continue
        implicit_route = implicit.get("path")
        implicit_rel = implicit.get("file")
        if not isinstance(implicit_route, str) or not isinstance(implicit_rel, str):
            continue
        if not (repo_root / implicit_rel).is_file():
            continue
        record = _candidate("gui_route", implicit_rel, detail=implicit_route)
        records.append(record)
        route_records.append(record)

    non_route_text = "\n".join(
        text
        for path, text in all_frontend_text.items()
        if path not in route_files
    )
    for route_record in route_records:
        route = route_record["detail"]
        if route in {"/", "*"} or route.startswith("*"):
            continue
        token = route
        if ":" in token:
            token = token.split(":", 1)[0]
        token = token.rstrip("/") or "/"
        if token not in non_route_text:
            records.append(
                _candidate(
                    "gui_unreachable",
                    route_record["path"],
                    detail=route,
                    line=route_record.get("line"),
                )
            )
    return records


def discover_candidates(
    repo_root: Path, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    # Resolve once so relative_to() sees the same form as the resolved paths
    # _iter_files produces (macOS tempdirs alias /var -> /private/var).
    repo_root = repo_root.resolve()
    discovery = manifest.get("discovery", {})
    records = [
        *_discover_python(repo_root, discovery),
        *_discover_frontend(repo_root, discovery),
    ]
    deduped = {record["id"]: record for record in records}
    return [deduped[key] for key in sorted(deduped)]


def _path_values(capability: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for area in ("backend", "analysis", "frontend"):
        block = capability.get(area, {})
        if not isinstance(block, dict):
            continue
        for field in ("files", "components", "discoverability"):
            raw = block.get(field, [])
            if isinstance(raw, list):
                values.extend((f"{area}.{field}", str(value)) for value in raw)
    tests = capability.get("tests", {})
    if isinstance(tests, dict):
        for field, raw in tests.items():
            if isinstance(raw, list):
                values.extend((f"tests.{field}", str(value)) for value in raw)
    return values


def _candidate_indexes(
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    by_id = {item["id"]: item for item in candidates}
    by_kind: dict[str, set[str]] = {}
    for item in candidates:
        by_kind.setdefault(item["kind"], set()).add(item["id"])
    return by_id, by_kind


def mapped_candidate_ids(
    manifest: dict[str, Any], candidates: list[dict[str, Any]]
) -> set[str]:
    mapped: set[str] = set()
    by_id, _ = _candidate_indexes(candidates)
    for capability in manifest.get("capabilities", []):
        if capability.get("status") == "legacy":
            continue
        mapped.update(
            value
            for value in capability.get("candidate_ids", [])
            if value in by_id
        )

        for area in ("backend", "analysis"):
            block = capability.get(area, {})
            if not isinstance(block, dict):
                continue
            files = set(block.get("files", []))
            endpoints = set(block.get("endpoints", []))
            symbols = set(block.get("symbols", []))
            for item in candidates:
                if item["kind"] == "backend_endpoint":
                    if item.get("detail") in endpoints and (
                        not files or item["path"] in files
                    ):
                        mapped.add(item["id"])
                elif item["kind"] in {
                    "python_module",
                    "analysis_module",
                    "cli_surface",
                }:
                    if item["path"] in files:
                        mapped.add(item["id"])
                elif item["kind"] in {"python_symbol", "analysis_symbol"}:
                    ref = f"{item['path']}:{item.get('symbol', '')}"
                    if ref in symbols or (not symbols and item["path"] in files):
                        mapped.add(item["id"])

        frontend = capability.get("frontend", {})
        if isinstance(frontend, dict):
            routes = set(frontend.get("routes", []))
            components = set(frontend.get("components", []))
            for item in candidates:
                if item["kind"] in {"gui_route", "gui_unreachable"}:
                    if item.get("detail") in routes:
                        mapped.add(item["id"])
                elif item["kind"] in {
                    "gui_page",
                    "gui_control",
                    "dead_control",
                    "mock_marker",
                    "frontend_api_client",
                } and item["path"] in components:
                    mapped.add(item["id"])
    return mapped


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_manifest(
    repo_root: Path,
    manifest: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> list[dict[str, str]]:
    today = today or datetime.now(timezone.utc).date()
    issues: list[dict[str, str]] = []

    def add(code: str, message: str, capability_id: str = "") -> None:
        issues.append(
            {
                "code": code,
                "message": message,
                **({"capability_id": capability_id} if capability_id else {}),
            }
        )

    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        add(
            "INVALID_MANIFEST_SCHEMA",
            f"schema_version must be {MANIFEST_SCHEMA!r}",
        )

    ids: set[str] = set()
    endpoint_details = {
        (item["path"], item.get("detail"))
        for item in candidates
        if item["kind"] == "backend_endpoint"
    }
    route_details = {
        item.get("detail")
        for item in candidates
        if item["kind"] == "gui_route"
    }
    unreachable_routes = {
        item.get("detail")
        for item in candidates
        if item["kind"] == "gui_unreachable"
    }

    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list):
        add("INVALID_CAPABILITIES", "capabilities must be a list")
        capabilities = []

    for capability in capabilities:
        if not isinstance(capability, dict):
            add("INVALID_CAPABILITY", "each capability must be an object")
            continue
        capability_id = str(capability.get("id", "")).strip()
        if not capability_id:
            add("MISSING_CAPABILITY_ID", "capability id is required")
            continue
        if capability_id in ids:
            add("DUPLICATE_CAPABILITY_ID", capability_id, capability_id)
        ids.add(capability_id)

        classification = capability.get("classification")
        status = capability.get("status")
        if classification not in CLASSIFICATIONS:
            add(
                "INVALID_CLASSIFICATION",
                f"{classification!r} is not allowed",
                capability_id,
            )
        if status not in STATUSES:
            add("INVALID_STATUS", f"{status!r} is not allowed", capability_id)
            continue

        for field, rel in _path_values(capability):
            if not (repo_root / rel).is_file():
                add(
                    "MISSING_CONTRACT_PATH",
                    f"{field} path does not exist: {rel}",
                    capability_id,
                )

        backend = capability.get("backend", {})
        analysis = capability.get("analysis", {})
        frontend = capability.get("frontend", {})
        tests = capability.get("tests", {})
        backend_present = bool(
            isinstance(backend, dict)
            and (
                backend.get("files")
                or backend.get("endpoints")
                or backend.get("symbols")
            )
        )
        analysis_present = bool(
            isinstance(analysis, dict)
            and (
                analysis.get("files")
                or analysis.get("endpoints")
                or analysis.get("symbols")
            )
        )
        frontend_present = bool(
            isinstance(frontend, dict)
            and (frontend.get("routes") or frontend.get("components"))
        )

        if status == "active":
            if classification in {"user", "operator", "analysis"}:
                if not (backend_present or analysis_present):
                    add(
                        "GUI_NOT_BACKEND_WIRED",
                        "active human-facing capability has no backend/analysis binding",
                        capability_id,
                    )
                if not frontend_present:
                    add(
                        "BACKEND_NOT_GUI_SURFACED",
                        "active human-facing capability has no GUI binding",
                        capability_id,
                    )
            if classification == "client_only":
                if not frontend_present:
                    add(
                        "MISSING_GUI_BINDING",
                        "active client-only capability has no GUI binding",
                        capability_id,
                    )
                if backend_present or analysis_present:
                    add(
                        "INVALID_CLIENT_ONLY_BINDING",
                        "client-only capability cannot claim a backend binding",
                        capability_id,
                    )
            if classification == "internal" and not capability.get("rationale"):
                add(
                    "MISSING_INTERNAL_RATIONALE",
                    "internal capability requires a rationale",
                    capability_id,
                )

            if classification != "internal":
                e2e = tests.get("e2e", []) if isinstance(tests, dict) else []
                if not e2e:
                    add(
                        "GUI_PATH_NOT_E2E_TESTED",
                        "active GUI capability requires tests.e2e",
                        capability_id,
                    )
                e2e_routes = (
                    frontend.get("e2e_routes", [])
                    if isinstance(frontend, dict)
                    else []
                )
                if not e2e_routes:
                    add(
                        "GUI_PATH_NOT_E2E_TESTED",
                        "active GUI capability requires frontend.e2e_routes",
                        capability_id,
                    )

            if capability.get("requires_terminal") is not False:
                add(
                    "TERMINAL_REQUIRED",
                    "active capability must declare requires_terminal=false",
                    capability_id,
                )

        if status == "staged":
            expiry = _parse_iso_date(capability.get("expires_on"))
            if not capability.get("feature_flag") or not capability.get("tracking"):
                add(
                    "INVALID_STAGED_CAPABILITY",
                    "staged capability requires feature_flag and tracking",
                    capability_id,
                )
            if expiry is None or expiry < today:
                add(
                    "EXPIRED_PARITY_EXCEPTION",
                    "staged capability expiry is missing, invalid, or expired",
                    capability_id,
                )

        if isinstance(backend, dict):
            files = set(backend.get("files", []))
            for endpoint in backend.get("endpoints", []):
                if not re.match(
                    r"^(GET|POST|PUT|PATCH|DELETE)\s+/\S*$", str(endpoint)
                ):
                    add(
                        "INVALID_ENDPOINT_BINDING",
                        f"invalid endpoint token: {endpoint}",
                        capability_id,
                    )
                    continue
                if not any(
                    detail == endpoint and (not files or path in files)
                    for path, detail in endpoint_details
                ):
                    add(
                        "MISSING_ENDPOINT_BINDING",
                        f"endpoint not found in configured backend files: {endpoint}",
                        capability_id,
                    )

        if isinstance(frontend, dict):
            routes = frontend.get("routes", [])
            for route in routes:
                if route not in route_details:
                    add(
                        "MISSING_GUI_ROUTE",
                        f"route not found in route table: {route}",
                        capability_id,
                    )
                if status == "active" and route in unreachable_routes:
                    add(
                        "GUI_WORKFLOW_UNREACHABLE",
                        f"route has no discoverable link outside the route table: {route}",
                        capability_id,
                    )
            for route in frontend.get("e2e_routes", []):
                if route not in routes:
                    add(
                        "INVALID_E2E_ROUTE",
                        f"e2e route is not declared in frontend.routes: {route}",
                        capability_id,
                    )

    for exception in manifest.get("exceptions", []):
        if not isinstance(exception, dict):
            add("INVALID_EXCEPTION", "each exception must be an object")
            continue
        required = ("id", "reason", "owner", "tracking", "expires_on", "candidate_ids")
        missing = [field for field in required if not exception.get(field)]
        if missing:
            add(
                "INVALID_EXCEPTION",
                f"exception missing: {', '.join(missing)}",
                str(exception.get("id", "")),
            )
        expiry = _parse_iso_date(exception.get("expires_on"))
        if expiry is None or expiry < today:
            add(
                "EXPIRED_PARITY_EXCEPTION",
                "exception expiry is missing, invalid, or expired",
                str(exception.get("id", "")),
            )

    return issues


def exception_candidate_ids(
    manifest: dict[str, Any], candidates: list[dict[str, Any]]
) -> set[str]:
    result: set[str] = set()
    for exception in manifest.get("exceptions", []):
        if isinstance(exception, dict):
            result.update(str(value) for value in exception.get("candidate_ids", []))
            files = {str(value) for value in exception.get("candidate_files", [])}
            result.update(item["id"] for item in candidates if item["path"] in files)
    return result


def build_baseline(
    manifest: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    counts = Counter(item["signal"] for item in candidates)
    return {
        "schema_version": BASELINE_SCHEMA,
        "repository": manifest.get("repository"),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest_sha256": _sha256_json(manifest),
        "candidate_count": len(candidates),
        "signal_counts": dict(sorted(counts.items())),
        "candidates": candidates,
    }


def evaluate(
    manifest: dict[str, Any],
    baseline: dict[str, Any],
    candidates: list[dict[str, Any]],
    manifest_issues: list[dict[str, str]],
    *,
    strict: bool = False,
) -> tuple[dict[str, Any], bool]:
    baseline_candidates = baseline.get("candidates", [])
    baseline_ids: set[str] = set()
    for item in baseline_candidates:
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("id")
        if isinstance(candidate_id, str):
            baseline_ids.add(candidate_id)
    current_by_id = {item["id"]: item for item in candidates}
    current_ids = set(current_by_id)
    mapped = mapped_candidate_ids(manifest, candidates)
    exceptions = exception_candidate_ids(manifest, candidates)

    new_ids = sorted(current_ids - baseline_ids - mapped - exceptions)
    removed_ids = sorted(baseline_ids - current_ids)
    legacy_ids = sorted((current_ids & baseline_ids) - mapped - exceptions)
    new_findings = [current_by_id[value] for value in new_ids]
    legacy_findings = [current_by_id[value] for value in legacy_ids]

    errors = list(manifest_issues)
    for finding in new_findings:
        errors.append(
            {
                "code": finding["signal"],
                "message": f"new unpaired candidate: {finding['id']}",
            }
        )
    if strict:
        for finding in legacy_findings:
            errors.append(
                {
                    "code": finding["signal"],
                    "message": f"legacy parity debt: {finding['id']}",
                }
            )

    report = {
        "schema_version": REPORT_SCHEMA,
        "repository": manifest.get("repository"),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "strict" if strict else "ratchet",
        "passed": not errors,
        "summary": {
            "current_candidates": len(current_ids),
            "mapped_candidates": len(mapped & current_ids),
            "exception_candidates": len(exceptions & current_ids),
            "legacy_gaps": len(legacy_findings),
            "new_gaps": len(new_findings),
            "removed_baseline_candidates": len(removed_ids),
            "manifest_issues": len(manifest_issues),
        },
        "signal_counts": dict(
            sorted(Counter(item["signal"] for item in legacy_findings).items())
        ),
        "new_findings": new_findings,
        "legacy_findings": legacy_findings,
        "removed_baseline_candidate_ids": removed_ids,
        "manifest_issues": manifest_issues,
        "errors": errors,
    }
    return report, not errors


def _render_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "## Federation GUI Capability Parity",
        "",
        f"**Repository:** `{report.get('repository')}`  ",
        f"**Mode:** `{report.get('mode')}`  ",
        f"**Result:** {'PASS' if report.get('passed') else 'FAIL'}",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Current candidates | {summary['current_candidates']} |",
        f"| Mapped candidates | {summary['mapped_candidates']} |",
        f"| Legacy gaps | {summary['legacy_gaps']} |",
        f"| New gaps | {summary['new_gaps']} |",
        f"| Manifest issues | {summary['manifest_issues']} |",
        f"| Removed baseline candidates | {summary['removed_baseline_candidates']} |",
    ]
    if report.get("errors"):
        lines.extend(["", "### Blocking findings", ""])
        for issue in report["errors"][:50]:
            lines.append(f"- `{issue['code']}` — {issue['message']}")
    if report.get("signal_counts"):
        lines.extend(["", "### Legacy debt by signal", ""])
        for signal, count in report["signal_counts"].items():
            lines.append(f"- `{signal}`: {count}")
    return "\n".join(lines) + "\n"


def _print_console(report: dict[str, Any]) -> None:
    summary = report["summary"]
    result = "PASS" if report["passed"] else "FAIL"
    print(
        f"{result} gui-parity {report.get('repository')} "
        f"mode={report['mode']} current={summary['current_candidates']} "
        f"mapped={summary['mapped_candidates']} legacy={summary['legacy_gaps']} "
        f"new={summary['new_gaps']} manifest_issues={summary['manifest_issues']}"
    )
    for issue in report.get("errors", [])[:100]:
        print(f"{issue['code']}: {issue['message']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=".federation/gui-capabilities.json",
        help="repository-relative capability manifest",
    )
    parser.add_argument(
        "--baseline",
        default=".federation/gui-parity-baseline.json",
        help="repository-relative committed debt baseline",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="replace the baseline with the current discovered candidate inventory",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="optional repository-relative JSON report output",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on legacy debt as well as new debt and manifest violations",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="repository root (defaults to the parent of scripts/)",
    )
    args = parser.parse_args(argv)

    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[1]
    )
    manifest_path = repo_root / args.manifest
    baseline_path = repo_root / args.baseline

    try:
        manifest = _load_json(manifest_path)
        candidates = discover_candidates(repo_root, manifest)
        issues = validate_manifest(repo_root, manifest, candidates)
    except ValueError as exc:
        print(f"gui-parity: {exc}", file=sys.stderr)
        return 2

    if args.write_baseline:
        if issues:
            for issue in issues:
                print(f"{issue['code']}: {issue['message']}", file=sys.stderr)
            return 1
        _write_json(baseline_path, build_baseline(manifest, candidates))
        print(f"wrote {baseline_path} with {len(candidates)} candidates")
        return 0

    try:
        baseline = _load_json(baseline_path)
    except ValueError as exc:
        print(f"gui-parity: {exc}", file=sys.stderr)
        return 2
    if baseline.get("schema_version") != BASELINE_SCHEMA:
        print(
            f"gui-parity: baseline schema must be {BASELINE_SCHEMA!r}",
            file=sys.stderr,
        )
        return 2

    report, passed = evaluate(
        manifest, baseline, candidates, issues, strict=args.strict
    )
    if args.report:
        _write_json(repo_root / args.report, report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(_render_summary(report))
    _print_console(report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
