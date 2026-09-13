from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.verify_operator_corpus import verify as verify_operator_corpus


def verify_scope_bound_operator_corpus(
    *,
    root: Path,
    corpus_root: Path | None,
    truth_scope: dict[str, Any] | None,
    current_registry_total: int,
    current_registry_digest: str,
) -> dict[str, Any]:
    """Reverify a full operator corpus and bind it to one truth scope fail-closed.

    Stored authority booleans and caller-supplied corpus IDs are observations only.
    Authority is granted only by a fresh full-operator-snapshot verification whose
    corpus identity and live registry identity match the certification scope.
    """

    blockers: list[str] = []
    verification: dict[str, Any] | None = None

    if corpus_root is None:
        blockers.append("operator_corpus_root_not_supplied")
    if truth_scope is None:
        blockers.append("truth_scope_required_for_operator_corpus")

    scope_identity: dict[str, Any] = {}
    if truth_scope is not None:
        candidate = truth_scope.get("scope_identity")
        if isinstance(candidate, dict):
            scope_identity = candidate
        else:
            blockers.append("truth_scope_identity_missing_for_operator_corpus")

    scope_corpus_id = scope_identity.get("operator_corpus_id")
    if not isinstance(scope_corpus_id, str) or not scope_corpus_id:
        blockers.append("truth_scope_operator_corpus_id_missing")

    if corpus_root is not None:
        corpus_root = corpus_root.resolve()
        try:
            verification = verify_operator_corpus(
                root=root.resolve(),
                corpus_root=corpus_root,
                require_operator_snapshot=True,
            )
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            blockers.append(f"operator_corpus_reverification_error:{type(exc).__name__}")

    if verification is None:
        return {
            "authoritative": False,
            "blockers": sorted(set(blockers)),
            "corpus_root": str(corpus_root) if corpus_root is not None else None,
            "scope_operator_corpus_id": scope_corpus_id,
            "verification": None,
        }

    verification_scope = verification.get("verification_scope")
    if not isinstance(verification_scope, dict):
        verification_scope = {}
        blockers.append("operator_corpus_verification_scope_missing")
    if verification_scope.get("operator_snapshot_required") is not True:
        blockers.append("operator_corpus_not_full_snapshot_verification")
    if verification_scope.get("mode") != "full_operator_snapshot":
        blockers.append("operator_corpus_verification_mode_mismatch")
    if verification.get("verified") is not True:
        blockers.append("operator_corpus_reverification_failed")
    if verification.get("operator_corpus_authoritative") is not True:
        blockers.append("operator_corpus_authority_not_proven")

    corpus_id = verification.get("corpus_id")
    computed_corpus_id = verification.get("computed_corpus_id")
    if not isinstance(corpus_id, str) or not corpus_id:
        blockers.append("operator_corpus_id_missing")
    if corpus_id != computed_corpus_id:
        blockers.append("operator_corpus_id_recomputation_mismatch")
    if scope_corpus_id != corpus_id:
        blockers.append("truth_scope_operator_corpus_id_mismatch")

    registry = verification.get("registry")
    if not isinstance(registry, dict):
        registry = {}
        blockers.append("operator_corpus_registry_identity_missing")
    if registry.get("total_sources") != current_registry_total:
        blockers.append("operator_corpus_registry_total_mismatch")
    if registry.get("source_ids_sha256") != current_registry_digest:
        blockers.append("operator_corpus_registry_digest_mismatch")

    if verification.get("manifest_source_count") != current_registry_total:
        blockers.append("operator_corpus_manifest_source_count_mismatch")

    inventory = verification.get("processed_file_inventory")
    if not isinstance(inventory, dict):
        inventory = {}
        blockers.append("operator_corpus_processed_inventory_missing")
    if inventory.get("orphan_mounted_files") not in ([], None):
        blockers.append("operator_corpus_orphan_mounted_files")
    if inventory.get("unreceipted_operator_files") not in ([], None):
        blockers.append("operator_corpus_unreceipted_operator_files")
    if inventory.get("accounted_outputs_missing_from_operator") not in ([], None):
        blockers.append("operator_corpus_accounted_outputs_missing_from_operator")

    verification_errors = verification.get("errors")
    if verification_errors not in ([], None):
        blockers.append("operator_corpus_verification_errors_present")

    blockers = sorted(set(blockers))
    return {
        "authoritative": not blockers,
        "blockers": blockers,
        "corpus_root": str(corpus_root) if corpus_root is not None else None,
        "scope_operator_corpus_id": scope_corpus_id,
        "corpus_id": corpus_id,
        "computed_corpus_id": computed_corpus_id,
        "registry": registry,
        "processed_file_inventory": inventory,
        "manifest_source_count": verification.get("manifest_source_count"),
        "manifest_product_count": verification.get("manifest_product_count"),
        "verification_scope": verification_scope,
        "verification_errors": verification_errors,
        "verification": verification,
    }
