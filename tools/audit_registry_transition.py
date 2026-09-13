"""Compare registry definitions at immutable Git revisions; never grant authority.

The certification-loader profile is explicit: root YAML plus direct JSON extensions.
Runtime JSON and overrides are frozen separately; divergence blocks equivalence.
Other extension formats remain inventoried, not silently promoted into either profile.
Only Git object reads are performed. No network, source execution, or ref writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

PROFILE = "moneysweep.certification-yaml-direct-json-extensions/v1"
RUNTIME_REGISTRY = "registries/source_registry.json"
OVERRIDES = "registries/source_registry_overrides/"
EXTENSIONS = "registries/source_registry_extensions/"
ROOT_REGISTRY = "registries/source_registry.yaml"
SHA = re.compile(r"[0-9a-f]{40}\Z")


class RegistryTransitionError(ValueError):
    """An input or observation is insufficient for this bounded audit."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise RegistryTransitionError(f"duplicate_mapping_key:{key}")
        out[key] = value
    return out


class _UniqueLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader: _UniqueLoader, node: yaml.MappingNode) -> dict[str, Any]:
    # YAML merge keys and non-string keys would obscure whole-record provenance.
    pairs = []
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise RegistryTransitionError("yaml_merge_keys_not_supported")
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise RegistryTransitionError("non_string_mapping_key")
        pairs.append((key, loader.construct_object(value_node, deep=True)))
    return _pairs(pairs)


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def canonical(value: object) -> bytes:
    """Repository Python JSON profile, explicitly not an RFC 8785 assertion."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise RegistryTransitionError("noncanonical_or_recursive_value") from exc


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _nonfinite(value: str) -> None:
    raise RegistryTransitionError("nonfinite_json_number:" + value)


def parse_registry(raw: bytes, path: str) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8-sig")
        value = (json.loads(text, object_pairs_hook=_pairs, parse_constant=_nonfinite)
                 if path.endswith(".json") else yaml.load(text, Loader=_UniqueLoader))
        canonical(value)  # Reject overflowed JSON floats and unsupported YAML scalar types.
    except (UnicodeError, yaml.YAMLError, json.JSONDecodeError) as exc:
        raise RegistryTransitionError(f"registry_parse_error:{path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("sources"), list):
        raise RegistryTransitionError(f"registry_sources_list_missing:{path}")
    sources = value["sources"]
    for source in sources:
        if not isinstance(source, dict):
            raise RegistryTransitionError(f"source_not_object:{path}")
        sid = source.get("source_id")
        if not isinstance(sid, str) or not sid or sid != sid.strip():
            raise RegistryTransitionError(f"invalid_raw_source_id:{path}")
        if type(source.get("required")) is not bool:
            raise RegistryTransitionError(f"required_not_boolean:{sid}")
    return sources


def git(root: Path, *args: str) -> bytes:
    # Ignore inherited Git overrides without inspecting credentials or their values.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            check=True, capture_output=True, timeout=30, env=env,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RegistryTransitionError("git_object_read_failed:" + args[0]) from exc


def _revision(root: Path, revision: str) -> None:
    if not SHA.fullmatch(revision):
        raise RegistryTransitionError("exact_lowercase_commit_sha_required")
    if git(root, "cat-file", "-t", revision).strip() != b"commit":
        raise RegistryTransitionError("revision_not_commit")


def snapshot(root: Path, revision: str) -> dict[str, Any]:
    _revision(root, revision)
    raw_tree = git(root, "ls-tree", "-rz", "--full-tree", revision,
                   ROOT_REGISTRY, RUNTIME_REGISTRY, EXTENSIONS.rstrip("/"), OVERRIDES.rstrip("/"))
    inventory: dict[str, dict[str, str]] = {}
    for entry in raw_tree.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise RegistryTransitionError("git_tree_entry_unreadable") from exc
        if path in inventory:
            raise RegistryTransitionError("duplicate_tree_path:" + path)
        inventory[path] = {"mode": mode, "type": kind, "git_blob_sha1": oid}
    if ROOT_REGISTRY not in inventory:
        raise RegistryTransitionError("root_registry_missing")
    selected = sorted(path for path in inventory if path == ROOT_REGISTRY or (
        path.startswith(EXTENSIONS) and "/" not in path[len(EXTENSIONS):]
        and path.endswith(".json")))
    sources: dict[str, dict[str, Any]] = {}
    retained: dict[str, bytes] = {}
    artifacts: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    for path, entry in sorted(inventory.items()):
        if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
            raise RegistryTransitionError("nonregular_registry_entry:" + path)
        raw = git(root, "cat-file", "blob", entry["git_blob_sha1"])
        observed_oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if observed_oid != entry["git_blob_sha1"]:
            raise RegistryTransitionError("git_blob_identity_mismatch:" + path)
        retained[path] = raw
        artifact = {"path": path, **entry, "bytes": len(raw), "sha256": sha256(raw)}
        if path not in selected:
            outside.append(artifact)
            continue
        rows = parse_registry(raw, path)
        artifact["source_count"] = len(rows)
        artifacts.append(artifact)
        for row in rows:
            sid = row["source_id"]
            if sid in sources:
                raise RegistryTransitionError("duplicate_source_id:" + sid)
            sources[sid] = {"definition": row, "definition_sha256": sha256(canonical(row)),
                            "manifestation_path": path}
    runtime = runtime_profile(retained)
    ids = sorted(sources)
    return {
        "runtime_profile": runtime,
        "commit_sha": revision, "loader_profile": PROFILE, "active_artifacts": artifacts,
        "outside_loader_profile": outside, "sources": sources,
        "total_sources": len(ids),
        "required_ids": sorted(sid for sid in ids if sources[sid]["definition"]["required"]),
        "source_ids_sha256": sha256(("\n".join(ids) + "\n").encode("utf-8")),
        "registry_definition_sha256": sha256(canonical({
            sid: sources[sid]["definition"] for sid in ids})),
    }



def runtime_profile(retained: dict[str, bytes]) -> dict[str, Any]:
    """Replay the separately identified runtime loader without importing its code."""
    if RUNTIME_REGISTRY not in retained:
        return {"state": "UNAVAILABLE", "sources": {}, "reason": "runtime_registry_missing"}
    selected = [RUNTIME_REGISTRY] + sorted(path for path in retained if (
        path.startswith(EXTENSIONS) and "/" not in path[len(EXTENSIONS):]
        and path.endswith(".json")))
    rows: dict[str, dict[str, Any]] = {}
    for path in selected:
        for row in parse_registry(retained[path], path):
            sid = row["source_id"]
            if sid in rows:
                raise RegistryTransitionError("runtime_duplicate_source_id:" + sid)
            rows[sid] = dict(row)
    overridden: set[str] = set()
    override_paths = sorted(path for path in retained if path.startswith(OVERRIDES)
                            and "/" not in path[len(OVERRIDES):] and path.endswith(".json"))
    for path in override_paths:
        try:
            document = json.loads(retained[path].decode("utf-8-sig"),
                                  object_pairs_hook=_pairs, parse_constant=_nonfinite)
            canonical(document)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RegistryTransitionError("override_parse_error:" + path) from exc
        if not isinstance(document, dict) or not isinstance(document.get("source_overrides"), list):
            raise RegistryTransitionError("override_list_missing:" + path)
        for override in document["source_overrides"]:
            if not isinstance(override, dict):
                raise RegistryTransitionError("override_not_object")
            sid = override.get("source_id")
            if not isinstance(sid, str) or not sid or sid != sid.strip():
                raise RegistryTransitionError("override_raw_id_invalid")
            if sid not in rows or sid in overridden:
                raise RegistryTransitionError("override_unknown_or_duplicate_id:" + sid)
            overridden.add(sid)
            if "required" in override and (type(override["required"]) is not bool
                    or override["required"] != rows[sid]["required"]):
                raise RegistryTransitionError("override_required_change:" + sid)
            rows[sid] = {**rows[sid], **override}
    return {"state": "REPLAYED", "loader_profile": "runtime-json-extensions-overrides/v1",
            "sources": rows, "input_paths": selected + override_paths,
            "required_ids": sorted(sid for sid, row in rows.items() if row["required"])}


def set_metrics(a: set[str], b: set[str]) -> dict[str, Any]:
    groups = {"INTERSECTION": sorted(a & b), "A_ONLY": sorted(a - b),
              "B_ONLY": sorted(b - a), "UNION": sorted(a | b),
              "SYMMETRIC_DIFFERENCE": sorted(a ^ b)}
    counts = {name: len(values) for name, values in groups.items()}
    if len(a) + len(b) != counts["UNION"] + counts["INTERSECTION"]:
        raise RegistryTransitionError("set_arithmetic_does_not_close")
    return {"members": groups, "counts": counts, "A_total": len(a), "B_total": len(b)}


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if a["loader_profile"] != b["loader_profile"]:
        raise RegistryTransitionError("loader_profiles_noncomparable")
    left, right = a["sources"], b["sources"]
    definitions = []
    for sid in sorted(set(left) & set(right)):
        old, new = left[sid]["definition"], right[sid]["definition"]
        if canonical(old) != canonical(new):
            keys = sorted(set(old) | set(new))
            definitions.append({
                "source_id": sid, "decision": "REVIEW", "class": "SOURCE_DEFINITION",
                "A_sha256": left[sid]["definition_sha256"],
                "B_sha256": right[sid]["definition_sha256"],
                "field_deltas": [{"field": key, "A_present": key in old, "B_present": key in new,
                                  "A": old.get(key), "B": new.get(key)} for key in keys
                                 if key not in old or key not in new
                                 or canonical(old[key]) != canonical(new[key])],
            })
    ids = set_metrics(set(left), set(right))
    required = set_metrics(set(a["required_ids"]), set(b["required_ids"]))
    ao = {x["path"]: x["git_blob_sha1"] for x in a["outside_loader_profile"]}
    bo = {x["path"]: x["git_blob_sha1"] for x in b["outside_loader_profile"]}
    outside_changes = [p for p in sorted(set(ao) | set(bo)) if ao.get(p) != bo.get(p)]
    blockers = []
    cross_profile = {}
    for label, snap in (("A", a), ("B", b)):
        runtime = snap.get("runtime_profile", {})
        if runtime.get("state") != "REPLAYED":
            blockers.append("runtime_profile_unverified:" + label)
            cross_profile[label] = {"state": "UNVERIFIED"}
            continue
        cert_rows = {sid: row["definition"] for sid, row in snap["sources"].items()}
        runtime_rows = runtime["sources"]
        profile_ids = set_metrics(set(cert_rows), set(runtime_rows))
        profile_deltas = sorted(sid for sid in set(cert_rows) & set(runtime_rows)
                                if canonical(cert_rows[sid]) != canonical(runtime_rows[sid]))
        cross_profile[label] = {"source_id_sets": profile_ids,
                                "changed_definition_ids": profile_deltas}
        if profile_ids["counts"]["SYMMETRIC_DIFFERENCE"] or profile_deltas:
            blockers.append("runtime_certification_profile_divergence:" + label)
    if ids["counts"]["SYMMETRIC_DIFFERENCE"]:
        blockers.append("source_id_population_changed")
    if required["counts"]["SYMMETRIC_DIFFERENCE"]:
        blockers.append("required_source_population_changed")
    if definitions:
        blockers.append("source_definitions_changed_receipts_not_inheritable")
    if outside_changes:
        blockers.append("outside_loader_manifestations_changed_requires_review")
    return {"schema_version": "moneysweep.registry_transition_audit/v1",
            "state": "AUDIT_ONLY", "production_eligible": False,
            "loader_profile": PROFILE, "source_id_sets": ids, "required_id_sets": required,
            "definition_changes": definitions, "outside_loader_changes": outside_changes,
            "cross_profile_comparison": cross_profile,
            "A_snapshot": a, "B_snapshot": b, "blockers": blockers,
            "identity_scope": "registry_source_definitions_not_organization_identity",
            "equivalence_decision": "UNPROVEN" if blockers else "IDENTICAL_ACTIVE_DEFINITIONS"}


def audit(root: Path, a_sha: str, b_sha: str) -> dict[str, Any]:
    return compare(snapshot(root, a_sha), snapshot(root, b_sha))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--a-sha", required=True)
    parser.add_argument("--b-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-identical", action="store_true")
    args = parser.parse_args()
    try:
        report = audit(args.root, args.a_sha, args.b_sha)
        payload = canonical(report) + b"\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(payload)
    except (OSError, RegistryTransitionError) as exc:
        print(json.dumps({"state": "BLOCKED", "error": str(exc), "production_eligible": False}))
        return 2
    print(json.dumps({"state": report["state"], "sha256": sha256(payload),
                      "counts": report["source_id_sets"]["counts"],
                      "blockers": report["blockers"]}, sort_keys=True))
    return 2 if args.require_identical and report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
