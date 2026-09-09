#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=False, capture_output=True, text=True
    )


def is_allowed_path(path: str, allowed_paths: list[str]) -> bool:
    return any(
        path == allowed or (allowed.endswith("/") and path.startswith(allowed))
        for allowed in allowed_paths
    )


def validate(
    root: Path,
    enforce_change_scope: bool = False,
    change_base: str | None = None,
) -> dict[str, Any]:
    skillpack_root = root / ".claude" / "skillpacks"
    errors = []
    binding = load_json(skillpack_root / "BINDING.json")
    manifest = load_json(skillpack_root / "MANIFEST.json")
    legacy = load_json(skillpack_root / "LEGACY_COMPATIBILITY.json")
    skill_bytes = (skillpack_root / "SKILL.md").read_bytes()
    skill_text = skill_bytes.decode("utf-8")
    if manifest["repository"] != binding["repository"]:
        errors.append("repository identity mismatch")
    if manifest["pinned_base_commit"] != binding["pinned_base_commit"]:
        errors.append("pinned base mismatch")
    if manifest.get("runtime_enabled") is not False:
        errors.append("runtime is not fail-closed")
    if any(v is not False for v in binding["activation"].values()):
        errors.append("activation boundary is not fail-closed")
    if any(v is not False for v in binding["authority"].values()):
        errors.append("authority boundary is not fail-closed")
    if sha256_bytes(skill_bytes) != manifest["skill_sha256"]:
        errors.append("skill SHA-256 mismatch")
    if len(skill_bytes) != manifest["skill_bytes"]:
        errors.append("skill size mismatch")
    capabilities = manifest["capabilities"]
    ids = {c["id"] for c in capabilities}
    if len(ids) != manifest["capability_count"]:
        errors.append("capability count mismatch")
    for c in capabilities:
        cid = c["id"]
        anchor = c.get("anchor")
        if not c.get("status"):
            errors.append(f"blank capability status: {cid}")
        if not c.get("preserved_responsibility"):
            errors.append(f"blank preserved responsibility: {cid}")
        if not anchor or f'<a id="{anchor}"></a>' not in skill_text:
            errors.append(f"missing capability anchor: {cid}")
        if f"`{cid}`" not in skill_text:
            errors.append(f"missing capability in dispatcher: {cid}")
        replacement = c.get("replacement")
        if replacement and replacement not in ids:
            errors.append(f"missing alias target for: {cid}")
    legacy_entries = legacy.get("entries", [])
    repo_ids = set(binding["capability_ids"])
    legacy_ids = {e["capability_id"] for e in legacy_entries}
    if legacy_ids != repo_ids:
        errors.append("legacy parity mismatch")
    if legacy.get("protected_legacy_surfaces", []) != binding.get("legacy_surfaces", []):
        errors.append("protected legacy surface mismatch")
    for e in legacy_entries:
        cid = e["capability_id"]
        if e.get("status") != "compatibility_shim":
            errors.append(f"legacy entry is not compatibility shim: {cid}")
        if e.get("capability_preserved") is not True:
            errors.append(f"legacy capability is not preserved: {cid}")
        if e.get("protected_legacy_surfaces", []) != binding.get("legacy_surfaces", []):
            errors.append(f"entry protected surface mismatch: {cid}")
        target = e.get("unified_target", "")
        prefix = ".claude/skillpacks/SKILL.md#"
        if not target.startswith(prefix):
            errors.append(f"invalid unified target: {cid}")
        elif f'<a id="{target[len(prefix) :]}"></a>' not in skill_text:
            errors.append(f"missing unified target anchor: {cid}")
        replacement = e.get("replacement")
        if replacement and replacement not in ids:
            errors.append(f"invalid legacy replacement target: {cid}")
    legacy_bytes = (skillpack_root / "LEGACY_COMPATIBILITY.json").read_bytes()
    if sha256_bytes(legacy_bytes) != manifest["legacy_compatibility_sha256"]:
        errors.append("legacy compatibility SHA-256 mismatch")
    for bound_path in binding["implementation_roots"] + binding["test_roots"]:
        if not (root / bound_path).exists():
            errors.append(f"bound path is missing: {bound_path}")
    checks = [
        "identity",
        "non_activation",
        "skill_hash",
        "capability_accounting",
        "dispatch_metadata",
        "anchor_resolution",
        "alias_resolution",
        "fail_closed_dispatch",
        "legacy_parity",
        "compatibility_targets",
        "surface_separation",
        "repository_path_bindings",
    ]
    if (root / ".git").exists():
        base = binding["pinned_base_commit"]
        shallow = run_git(root, "rev-parse", "--is-shallow-repository")
        is_shallow = shallow.returncode == 0 and shallow.stdout.strip() == "true"
        base_obj = run_git(root, "cat-file", "-e", f"{base}^{{commit}}")
        if base_obj.returncode != 0:
            if is_shallow:
                checks.append("git_history_deferred_shallow_checkout")
            else:
                errors.append("pinned base commit object is unavailable")
        else:
            if run_git(root, "merge-base", "--is-ancestor", base, "HEAD").returncode != 0:
                errors.append("pinned base is not an ancestor of HEAD")
            else:
                checks.append("pinned_base_ancestry")

        if enforce_change_scope:
            scope_base = change_base or base
            scope_base_obj = run_git(
                root, "cat-file", "-e", f"{scope_base}^{{commit}}"
            )
            if scope_base_obj.returncode != 0:
                errors.append("change base commit object is unavailable")
                changed: list[str] = []
            elif (
                run_git(
                    root, "merge-base", "--is-ancestor", scope_base, "HEAD"
                ).returncode
                != 0
            ):
                errors.append("change base is not an ancestor of HEAD")
                changed = []
            else:
                diff = run_git(root, "diff", "--name-only", f"{scope_base}..HEAD")
                if diff.returncode != 0:
                    errors.append("git diff failed")
                    changed = []
                else:
                    changed = [p for p in diff.stdout.splitlines() if p]

            allowed = manifest["allowed_change_paths"]
            for p in changed:
                if not is_allowed_path(p, allowed):
                    errors.append(f"out-of-scope change: {p}")
            for surface in binding.get("legacy_surfaces", []):
                prefix = surface.rstrip("/") + "/"
                for p in changed:
                    if p == surface or p.startswith(prefix):
                        errors.append(f"legacy surface was modified: {surface}")
            checks += [
                "change_base_ancestry",
                "change_scope",
                "legacy_non_modification",
            ]
    return {
        "schema_version": "1.0",
        "repository": binding["repository"],
        "pinned_base_commit": binding["pinned_base_commit"],
        "status": "success" if not errors else "failed",
        "checks": checks,
        "errors": errors,
        "capability_count": manifest["capability_count"],
        "module_count": manifest["module_count"],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--enforce-change-scope", action="store_true")
    p.add_argument(
        "--change-base",
        help="commit used for changed-path enforcement (defaults to pinned base)",
    )
    args = p.parse_args()
    result = validate(
        Path(args.root).resolve(),
        enforce_change_scope=args.enforce_change_scope,
        change_base=args.change_base,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
