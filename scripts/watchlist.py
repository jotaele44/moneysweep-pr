"""Read-only access + matching for repo watchlists (``registries/watchlists/*.json``).

A *watchlist* is a flagged reference list (e.g. entities from a criminal case)
that is deliberately **not** a source in the materialization registry. Its only
purpose is cross-referencing: when Contract-Sweeper acquires public-money data,
test incoming entity names against the watchlist and flag overlaps for human
review. See ``data/watchlists/<id>/README.md``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_DIR = REPO_ROOT / "registries" / "watchlists"

_LEADING_CODE = re.compile(r"^(?:to\s+)?\d+\s+", re.IGNORECASE)
_WS = re.compile(r"\s+")
# Minimum normalized length for a containment (substring) match. Shorter strings
# (e.g. "INC", "LLC") must match exactly, so generic suffixes don't over-flag.
_MIN_CONTAINMENT_LEN = 5


def normalize_entity(name: str) -> str:
    """Uppercase, drop a leading numeric ledger code, collapse punctuation/whitespace."""
    if not name:
        return ""
    s = _LEADING_CODE.sub("", str(name).strip())
    s = s.replace(".", " ").replace(",", " ")
    return _WS.sub(" ", s).strip().upper()


def _watchlist_dir(root: Path | None) -> Path:
    return (Path(root) / "registries" / "watchlists") if root else WATCHLIST_DIR


def load_watchlist(name: str, root: Path | None = None) -> dict:
    """Load a watchlist manifest by id (e.g. ``epstein_pr_case``)."""
    return json.loads((_watchlist_dir(root) / f"{name}.json").read_text(encoding="utf-8"))


def flagged_entities(name: str, root: Path | None = None) -> set[str]:
    """Normalized set of flagged entity names for a watchlist."""
    wl = load_watchlist(name, root)
    return {normalize_entity(e) for e in wl.get("flagged_entities", [])} - {""}


def match(value: str, name: str, root: Path | None = None) -> bool:
    """True if ``value`` overlaps a flagged entity in watchlist ``name``.

    Matches on the normalized form: exact match always; containment (either
    direction) only when both strings are at least ``_MIN_CONTAINMENT_LEN`` long,
    so short generic tokens like ``INC`` do not over-flag.
    """
    v = normalize_entity(value)
    if not v:
        return False
    for e in flagged_entities(name, root):
        if e == v:
            return True
        if len(e) >= _MIN_CONTAINMENT_LEN and len(v) >= _MIN_CONTAINMENT_LEN and (e in v or v in e):
            return True
    return False
