"""Shared runtime configuration loading for Contract Sweeper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import dotenv_values


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration for shared pipeline components."""

    project_root: Path
    configs_dir: Path
    cache_dir: Path
    manifests_dir: Path
    log_level: str
    environment: str


def _resolve_path(root: Path, value: str, default: str) -> Path:
    candidate = Path(value or default)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def load_runtime_config(project_root: Path | None = None) -> RuntimeConfig:
    """Load runtime config from environment with optional .env overlays."""

    root = (project_root or Path.cwd()).resolve()
    env_file = root / ".env"
    env_from_file = dotenv_values(env_file) if env_file.exists() else {}

    def env(key: str, default: str) -> str:
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
        from_file = env_from_file.get(key)
        if from_file is not None and str(from_file).strip() != "":
            return str(from_file).strip()
        return default

    configs_dir = _resolve_path(root, env("CONTRACT_SWEEPER_CONFIG_DIR", "configs"), "configs")
    cache_dir = _resolve_path(root, env("CONTRACT_SWEEPER_CACHE_DIR", "data/cache"), "data/cache")
    manifests_dir = _resolve_path(
        root,
        env("CONTRACT_SWEEPER_MANIFEST_DIR", "data/staging/manifests"),
        "data/staging/manifests",
    )

    return RuntimeConfig(
        project_root=root,
        configs_dir=configs_dir,
        cache_dir=cache_dir,
        manifests_dir=manifests_dir,
        log_level=env("CONTRACT_SWEEPER_LOG_LEVEL", "INFO").upper(),
        environment=env("CONTRACT_SWEEPER_ENV", "development"),
    )
