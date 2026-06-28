"""Read-only inventory of repo files declared in federation.json."""

from __future__ import annotations

import json
from pathlib import Path


def load_federation(root: Path) -> dict:
    path = root / "federation.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def collect_repo_state(root: Path) -> dict:
    fed = load_federation(root)
    outputs = fed.get("canonical_outputs", {})
    present = {key: (root / rel).exists() for key, rel in outputs.items() if isinstance(rel, str)}
    return {
        "federation_json_present": (root / "federation.json").exists(),
        "federation": fed,
        "canonical_outputs": outputs,
        "canonical_outputs_present": present,
    }
