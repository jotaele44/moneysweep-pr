"""Offline validator for a PRII skill packet — federation-wide, repo-portable.

Runs ten packet checks with no network and no live source acquisition:
structure, registry, command-resolution, path-resolution, boundary-policy,
mode-safety, coverage-accounting, export-contract, activation, drift.

This is the single Hub-owned validator; the same file is copied byte-identical
into every federation repo (moneysweep-pr, centinelas-pr, thehub-pr, …).
Repo-specific behavior is driven by a ``packet_config:`` block at the top of
``skill-registry.yaml`` — there are no repo names hardcoded here. Config keys:

  boundary_owner      expected skill boundary_owner (default: owner_repo basename)
  owner_repo          expected skill owner_repo (default: registry owner_repo)
  command_source      federation_json | manifest_file | cli_entrypoints
  command_source_ref  path to the command-map JSON (default: federation.json)
  command_key         key holding the command map (default: hub_callable_commands)
  available_commands  explicit command list (cli_entrypoints mode only)
  activation_routes   non-skill routes allowed in the activation matrix
  export_contract     optional {command_id, required_paths}; absent => no-op
  coverage_report     optional path to a readiness report; absent => no-op

Each check returns ``list[str]`` of errors (empty = pass). ``run_all``
aggregates them; the CLI exits non-zero on any failure. Stdlib + PyYAML only.

Usage:
  python3 scripts/validate_skills.py            # all checks, human output
  python3 scripts/validate_skills.py --json      # machine-readable
  python3 scripts/validate_skills.py --check command-resolution   # one check
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    # Raise rather than sys.exit() -- see the note in
    # scripts/regenerate_registry_json.py.
    raise ImportError("PyYAML is required: pip install PyYAML") from exc

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = "skills"
REGISTRY = "skill-registry.yaml"
ACTIVATION = "activation-matrix.yaml"
DEPENDENCY = "dependency-graph.yaml"

SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9-]+$")
ALLOWED_MODES = frozenset({"read_only", "offline_write", "live_network", "promotion"})
SAFE_DEFAULT_MODES = frozenset({"read_only", "offline_write"})
GATED_MODES = frozenset({"live_network", "promotion"})
# Skill-folder entries that are allowed (no skill-level README, per §3).
ALLOWED_SKILL_ENTRIES = frozenset({"SKILL.md", "agents", "references", "scripts"})
COMMAND_SOURCES = frozenset({"federation_json", "manifest_file", "cli_entrypoints"})


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def _load_yaml(root: Path, rel: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except OSError:
        return {}


def _load_json(root: Path, rel: str) -> dict[str, Any]:
    try:
        data = json.loads((root / rel).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _registry_skills(root: Path) -> list[dict[str, Any]]:
    return list(_load_yaml(root, REGISTRY).get("skills") or [])


def _packet_config(root: Path) -> dict[str, Any]:
    """Per-repo packet configuration (top of skill-registry.yaml)."""
    return _load_yaml(root, REGISTRY).get("packet_config") or {}


def _command_ids(root: Path, cfg: dict[str, Any]) -> set[str]:
    """The set of command IDs a skill may reference, per the packet's
    command_source: a JSON command map (federation_json / manifest_file) or an
    explicit list (cli_entrypoints, for repos with no federation manifest)."""
    source = cfg.get("command_source", "federation_json")
    if source == "cli_entrypoints":
        return {str(c) for c in (cfg.get("available_commands") or [])}
    ref = cfg.get("command_source_ref", "federation.json")
    key = cfg.get("command_key", "hub_callable_commands")
    return set(_load_json(root, ref).get(key) or {})


def _frontmatter(text: str) -> dict[str, Any] | None:
    """Parse a leading ``---`` YAML frontmatter block from a SKILL.md."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        block = yaml.safe_load(text[3:end])
        return block if isinstance(block, dict) else None
    except yaml.YAMLError:
        return None


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def check_skill_structure(root: Path) -> list[str]:
    errors: list[str] = []
    for skill in _registry_skills(root):
        sid = skill.get("skill_id", "<unknown>")
        folder = root / SKILLS_DIR / sid
        if not folder.is_dir():
            errors.append(f"{sid}: skills/{sid}/ directory is missing")
            continue
        if not SKILL_ID_RE.match(sid):
            errors.append(f"{sid}: folder name is not lowercase-hyphenated")
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"{sid}: SKILL.md is missing")
        else:
            fm = _frontmatter(skill_md.read_text(encoding="utf-8"))
            if fm is None:
                errors.append(f"{sid}: SKILL.md has no valid YAML frontmatter")
            else:
                for field in ("name", "description"):
                    if not fm.get(field):
                        errors.append(f"{sid}: SKILL.md frontmatter missing '{field}'")
                if fm.get("name") and fm["name"] != sid:
                    errors.append(f"{sid}: SKILL.md name '{fm['name']}' != folder id")
        if not (folder / "agents" / "openai.yaml").is_file():
            errors.append(f"{sid}: agents/openai.yaml is missing")
        for entry in folder.iterdir():
            if entry.name not in ALLOWED_SKILL_ENTRIES:
                errors.append(
                    f"{sid}: prohibited skill entry '{entry.name}' (no skill-level README)"
                )
    return errors


def _validate_contract_entry(skill: dict[str, Any]) -> list[str]:
    """Self-contained validation of one entry against prii_skill_contract_v1."""
    sid = skill.get("skill_id", "<unknown>")
    errors: list[str] = []
    required = (
        "schema_version",
        "skill_id",
        "owner_repo",
        "federation_role",
        "trigger_intents",
        "allowed_modes",
        "default_mode",
        "command_ids",
        "boundary_owner",
        "forbidden_operations",
        "stop_conditions",
        "evidence_requirements",
    )
    for field in required:
        if field not in skill:
            errors.append(f"{sid}: missing required contract field '{field}'")
    if skill.get("schema_version") != "prii_skill_contract_v1":
        errors.append(f"{sid}: schema_version must be prii_skill_contract_v1")
    if not SKILL_ID_RE.match(sid):
        errors.append(f"{sid}: skill_id is not lowercase-hyphenated")
    for list_field in (
        "trigger_intents",
        "stop_conditions",
        "evidence_requirements",
        "forbidden_operations",
    ):
        val = skill.get(list_field)
        if not isinstance(val, list) or not val:
            errors.append(f"{sid}: '{list_field}' must be a non-empty list")
    modes = skill.get("allowed_modes") or []
    bad_modes = set(modes) - ALLOWED_MODES
    if bad_modes:
        errors.append(f"{sid}: unknown allowed_modes {sorted(bad_modes)}")
    if skill.get("default_mode") not in ALLOWED_MODES:
        errors.append(f"{sid}: default_mode {skill.get('default_mode')!r} not a known mode")
    elif skill.get("default_mode") not in modes:
        errors.append(f"{sid}: default_mode not in allowed_modes")
    return errors


def check_skill_registry(root: Path) -> list[str]:
    errors: list[str] = []
    skills = _registry_skills(root)
    if not skills:
        return [f"{REGISTRY}: no skills declared or file unreadable"]
    ids = [str(s.get("skill_id")) for s in skills]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate skill_id(s): {sorted(dupes)}")
    for skill in skills:
        errors.extend(_validate_contract_entry(skill))
    # No orphan folders: every skills/<dir> must be registered.
    skills_root = root / SKILLS_DIR
    if skills_root.is_dir():
        registered = set(ids)
        for entry in skills_root.iterdir():
            if entry.is_dir() and entry.name not in registered:
                errors.append(f"orphan skill folder not in registry: skills/{entry.name}")
    return errors


def check_command_resolution(root: Path) -> list[str]:
    errors: list[str] = []
    cfg = _packet_config(root)
    source = cfg.get("command_source", "federation_json")
    if source not in COMMAND_SOURCES:
        return [f"packet_config.command_source '{source}' is not a known source"]
    commands = _command_ids(root, cfg)
    skills = _registry_skills(root)
    if not commands and any(s.get("command_ids") for s in skills):
        return [f"command source ({source}) resolved no commands but skills declare command_ids"]
    for skill in skills:
        sid = skill.get("skill_id", "<unknown>")
        for cid in skill.get("command_ids") or []:
            if cid not in commands:
                errors.append(f"{sid}: command_id '{cid}' does not resolve ({source})")
    return errors


def check_path_resolution(root: Path) -> list[str]:
    errors: list[str] = []
    root_resolved = root.resolve()
    for skill in _registry_skills(root):
        sid = skill.get("skill_id", "<unknown>")
        for key in ("local_scripts", "reads", "writes"):
            for rel in skill.get(key) or []:
                # writes may legitimately not exist yet; only path-check inputs.
                if key == "writes":
                    continue
                # Contract: these are repo-relative paths. Reject absolute paths
                # or ones that escape the repo root (../, symlink-free) — a skill
                # must not authorize resources outside the repository boundary.
                if Path(rel).is_absolute():
                    errors.append(f"{sid}: {key} path is not repo-relative: {rel}")
                    continue
                target = (root / rel).resolve()
                if target != root_resolved and root_resolved not in target.parents:
                    errors.append(f"{sid}: {key} path escapes the repo root: {rel}")
                    continue
                if not target.exists():
                    errors.append(f"{sid}: {key} path does not exist: {rel}")
    return errors


def check_boundary_policy(root: Path) -> list[str]:
    errors: list[str] = []
    cfg = _packet_config(root)
    owner = cfg.get("owner_repo") or _load_yaml(root, REGISTRY).get("owner_repo") or ""
    boundary = cfg.get("boundary_owner") or (owner.split("/")[-1] if owner else "")
    for skill in _registry_skills(root):
        sid = skill.get("skill_id", "<unknown>")
        if skill.get("owner_repo") != owner:
            errors.append(f"{sid}: owner_repo != registry owner {owner}")
        if boundary and skill.get("boundary_owner") != boundary:
            errors.append(f"{sid}: boundary_owner must be '{boundary}'")
        if not (skill.get("forbidden_operations") or []):
            errors.append(f"{sid}: forbidden_operations must be declared (boundary guard)")
    return errors


def check_mode_safety(root: Path) -> list[str]:
    errors: list[str] = []
    for skill in _registry_skills(root):
        sid = skill.get("skill_id", "<unknown>")
        default = skill.get("default_mode")
        if default not in SAFE_DEFAULT_MODES:
            errors.append(
                f"{sid}: default_mode '{default}' is not a safe default (read_only/offline_write)"
            )
        gated = set(skill.get("allowed_modes") or []) & GATED_MODES
        if gated and not (skill.get("requires_user_authorization") or []):
            errors.append(
                f"{sid}: {sorted(gated)} allowed but requires_user_authorization is empty"
            )
        for secret in skill.get("requires_secrets") or []:
            if "=" in secret or "/" in secret:
                errors.append(f"{sid}: requires_secrets must list names only, got {secret!r}")
    return errors


def check_coverage_accounting(root: Path) -> list[str]:
    """A declared readiness report must self-reconcile (blueprint §7 rule 4).

    Presence-enabled: repos without a coverage_report in packet_config skip
    this check (returns no errors)."""
    cfg = _packet_config(root)
    report = cfg.get("coverage_report")
    if not report:
        return []
    errors: list[str] = []
    r = _load_json(root, report)
    if not r:
        return [f"{report} unreadable"]
    total = r.get("total_sources")
    auto = r.get("automatable_total")
    queued_total = r.get("queued_excluded_total")
    queued = r.get("queued_excluded") or {}
    if isinstance(total, int) and isinstance(auto, int) and isinstance(queued_total, int):
        if auto + queued_total != total:
            errors.append(
                f"readiness: automatable({auto}) + queued({queued_total}) != total({total})"
            )
        if sum(queued.values()) != queued_total:
            errors.append(
                f"readiness: queued_excluded values sum {sum(queued.values())} != {queued_total}"
            )
    else:
        errors.append("readiness: total/automatable/queued counts are not all integers")
    if not (r.get("source_count_provenance") or {}).get("source_ids_sha256"):
        errors.append("readiness: missing source_ids_sha256 (registry hash provenance)")
    return errors


def check_export_contract(root: Path) -> list[str]:
    """A declared export contract: its command resolves and required paths exist.

    Presence-enabled: repos without an export_contract in packet_config skip
    this check (returns no errors)."""
    cfg = _packet_config(root)
    spec = cfg.get("export_contract")
    if not spec:
        return []
    errors: list[str] = []
    commands = _command_ids(root, cfg)
    cid = spec.get("command_id")
    if cid and cid not in commands:
        errors.append(f"export_contract command_id '{cid}' does not resolve")
    for rel in spec.get("required_paths") or []:
        if not (root / rel).exists():
            errors.append(f"export_contract required path missing: {rel}")
    return errors


def check_activation(root: Path) -> list[str]:
    """The activation matrix is the packet's prompt-routing coverage artifact, so
    a missing or empty matrix is a failure — not a silent pass. Every registered
    skill must have at least one positive case, and every case must route to a
    known skill or a declared route."""
    errors: list[str] = []
    cfg = _packet_config(root)
    routes = {str(r) for r in (cfg.get("activation_routes") or ["clarify"])}
    matrix = _load_yaml(root, ACTIVATION)
    if not matrix:
        return [f"{ACTIVATION} is missing or empty (activation coverage is required)"]
    buckets = {b: (matrix.get(b) or []) for b in ("positive", "negative", "ambiguous")}
    if not any(buckets.values()):
        errors.append(f"{ACTIVATION} declares no activation cases in any bucket")
    known = {s.get("skill_id") for s in _registry_skills(root)}
    for bucket, cases in buckets.items():
        for case in cases:
            expect = case.get("expect")
            if expect not in known and expect not in routes:
                errors.append(
                    f"activation[{bucket}]: expect '{expect}' is not a skill or known route"
                )
            if not case.get("prompt"):
                errors.append(f"activation[{bucket}]: a case is missing its prompt")
    covered = {case.get("expect") for case in buckets["positive"]}
    for sid in sorted(s for s in known if s):
        if sid not in covered:
            errors.append(f"activation: skill '{sid}' has no positive activation case")
    return errors


def check_drift(root: Path) -> list[str]:
    """Dependency-graph nodes + invariant targets must all be real skills, and
    every command a skill claims must still exist (stale-reference guard)."""
    errors: list[str] = []
    known = {s.get("skill_id") for s in _registry_skills(root)}
    graph = _load_yaml(root, DEPENDENCY)
    for parent, children in (graph.get("edges") or {}).items():
        for node in [parent, *children]:
            if node not in known:
                errors.append(f"dependency-graph node '{node}' is not a registered skill")
    for inv in graph.get("invariants") or []:
        for node in inv.get("applies_to") or []:
            if node not in known:
                errors.append(f"invariant '{inv.get('id')}' targets unknown skill '{node}'")
    if graph.get("root") and graph["root"] not in known:
        errors.append(f"dependency-graph root '{graph['root']}' is not a registered skill")
    return errors


CHECKS: dict[str, Callable[[Path], list[str]]] = {
    "skill-structure": check_skill_structure,
    "skill-registry": check_skill_registry,
    "command-resolution": check_command_resolution,
    "path-resolution": check_path_resolution,
    "boundary-policy": check_boundary_policy,
    "mode-safety": check_mode_safety,
    "coverage-accounting": check_coverage_accounting,
    "export-contract": check_export_contract,
    "activation": check_activation,
    "drift": check_drift,
}


def run_all(root: Path, only: str | None = None) -> dict[str, list[str]]:
    checks = {only: CHECKS[only]} if only else CHECKS
    return {name: fn(root) for name, fn in checks.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check", choices=sorted(CHECKS), help="run one check only")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    results = run_all(Path(args.root), only=args.check)
    total = sum(len(v) for v in results.values())
    if args.json:
        print(json.dumps({"ok": total == 0, "errors": results}, indent=2))
    else:
        for name, errs in results.items():
            mark = "ok" if not errs else "FAIL"
            print(f"[{mark}] {name}")
            for e in errs:
                print(f"    - {e}")
        print(f"\n{total} error(s) across {len(results)} check(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
