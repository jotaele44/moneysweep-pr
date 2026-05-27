"""Operator-curated alias overrides for entity clustering.

Loads ``registries/alias_overrides.yaml`` and exposes a mapping from any
observed alias (in its default-normalized form) to its canonical
normalized form.

Use ``load_overrides()`` once per process and pass the returned dict into
``apply()`` for every entity name encountered before clustering.

The override file is operator-curated and not a legal-identity assertion;
consumers must continue to honour ``docs/CLAIM_LANGUAGE_POLICY.md``.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from contract_sweeper.runtime.name_normalization import normalize_name

DEFAULT_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[2] / "registries" / "alias_overrides.yaml"
)


class AliasOverrideError(ValueError):
    """Raised when the override registry is malformed or contains cycles."""


def load_overrides(path: Path | None = None) -> dict[str, str]:
    """Return ``{normalized_alias: normalized_canonical}`` for every entry.

    Returns an empty dict if the file is missing. Raises
    :class:`AliasOverrideError` on malformed entries or cycles.
    """
    target = Path(path) if path is not None else DEFAULT_OVERRIDE_PATH
    if not target.exists():
        return {}
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AliasOverrideError(f"failed to parse {target}: {exc}") from exc

    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise AliasOverrideError(
            f"{target}: top-level 'entries' must be a list"
        )

    mapping: dict[str, str] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise AliasOverrideError(
                f"{target}: entry #{idx} is not a mapping"
            )
        canonical_raw = entry.get("canonical_name")
        if not canonical_raw:
            raise AliasOverrideError(
                f"{target}: entry #{idx} missing canonical_name"
            )
        canonical_norm = normalize_name(canonical_raw)
        if not canonical_norm:
            raise AliasOverrideError(
                f"{target}: entry #{idx} canonical_name normalizes to empty"
            )
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            raise AliasOverrideError(
                f"{target}: entry #{idx} aliases must be a list"
            )
        # Canonical maps to itself; aliases map to canonical.
        for alias in [canonical_raw, *aliases]:
            alias_norm = normalize_name(alias)
            if not alias_norm:
                continue
            existing = mapping.get(alias_norm)
            if existing and existing != canonical_norm:
                raise AliasOverrideError(
                    f"{target}: alias '{alias}' maps to both "
                    f"'{existing}' and '{canonical_norm}'"
                )
            mapping[alias_norm] = canonical_norm

    _check_cycles(mapping)
    return mapping


def _check_cycles(mapping: dict[str, str]) -> None:
    """Reject any cycle (a → b → a) in the alias graph."""
    for start in mapping:
        seen = {start}
        current = mapping[start]
        while current in mapping and mapping[current] != current:
            if current in seen:
                raise AliasOverrideError(
                    f"alias cycle detected starting at '{start}'"
                )
            seen.add(current)
            current = mapping[current]


def apply(name: str, overrides: dict[str, str]) -> tuple[str, bool]:
    """Return ``(canonical_normalized, was_overridden)`` for ``name``.

    If ``name`` (after default normalization) is not in ``overrides``,
    returns the default-normalized form and ``False``.
    """
    norm = normalize_name(name)
    if not norm:
        return "", False
    canonical = overrides.get(norm)
    if canonical and canonical != norm:
        return canonical, True
    return norm, False
