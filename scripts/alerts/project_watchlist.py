"""Load and normalize project-watchlist configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WATCHLIST_PATH = PROJECT_ROOT / "config" / "project_watchlist.yaml"
DEFAULT_THRESHOLDS_PATH = PROJECT_ROOT / "config" / "alert_thresholds.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required for project alert configuration")
    if not path.exists():
        raise FileNotFoundError(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_project_watchlist(path: str | Path = DEFAULT_WATCHLIST_PATH) -> list[dict[str, Any]]:
    config = _load_yaml(Path(path))
    projects = config.get("projects", [])
    if not isinstance(projects, list):
        raise ValueError("project_watchlist.yaml must define projects as a list")
    return projects


def load_alert_thresholds(path: str | Path = DEFAULT_THRESHOLDS_PATH) -> dict[str, Any]:
    config = _load_yaml(Path(path))
    config.setdefault("thresholds", {"watch": 35, "review": 55, "urgent": 75, "critical": 90})
    config.setdefault("scoring", {})
    config.setdefault("amount_thresholds", {"default_major_amount": 1_000_000})
    return config
