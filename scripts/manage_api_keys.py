"""
Read/write access to pipeline API keys, shared by scripts/set_api_key.py (CLI)
and server/backend/api_keys.py (dashboard endpoint).

.env.example is the source of truth for *which* keys exist (parsed at call
time, so the registry can't drift out of sync with the documented list); .env
is the source of truth for their *values*. Callers never see a stored value
back from this module except set_key()'s own caller, who already has it.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts.config import PROJECT_ROOT, _load_dotenv

ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"

# .env.example's own placeholder sentinel (see its header comment). A fresh
# .env seeded from .env.example, or one a contributor created by literally
# following SETUP.md's `cp .env.example .env`, carries this value verbatim —
# it must never count as "set".
PLACEHOLDER_VALUE = "paste_your_key_here"
MAX_KEY_VALUE_LENGTH = 8192
CREDENTIAL_NAME_SUFFIXES = (
    "_API_KEY",
    "_APP_TOKEN",
    "_LICENSE_APPROVED",
)


class UnknownKeyError(ValueError):
    """Raised when a caller requests a name outside the documented registry."""


class InvalidKeyValueError(ValueError):
    """Raised when a value cannot be represented safely in a dotenv line."""


@dataclass(frozen=True)
class KeyInfo:
    name: str
    description: str
    required: bool


def known_keys(example_path: Path | None = None) -> list[KeyInfo]:
    """Parse .env.example into the registry of known credential vars.

    Each KEY=value line's required-ness comes from the first word of its
    preceding comment block ("Required..." vs "Recommended"/"Optional...");
    its description is that block's last comment line.
    """
    # Resolved here (not as a `= ENV_EXAMPLE_PATH` default) so that patching
    # the module-level path after import — e.g. tests monkeypatching
    # ENV_EXAMPLE_PATH — is actually honored. A literal default is bound once
    # at def time and would silently ignore any later reassignment.
    if example_path is None:
        example_path = ENV_EXAMPLE_PATH
    if not example_path.exists():
        return []

    keys: list[KeyInfo] = []
    comment_block: list[str] = []
    for raw in example_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            # A blank line ends a comment block. Consecutive KEY=value lines
            # with no blank line between them (e.g. FINANCIALDATA_API_KEY /
            # FINANCIALDATA_LICENSE_APPROVED) intentionally share one block.
            comment_block = []
            continue
        if line.startswith("#"):
            comment_block.append(line.lstrip("#").strip())
            continue
        if "=" in line:
            name = line.split("=", 1)[0].strip()
            if not name.endswith(CREDENTIAL_NAME_SUFFIXES):
                continue
            description = comment_block[-1] if comment_block else ""
            # Scan the whole block (not just its first line) for the nearest
            # Required/Optional/Recommended marker: unrelated file-header
            # comments can precede the first key's block with no blank-line
            # separator (a bare "#" line doesn't count as blank), so the
            # marker isn't always line 0.
            required = False
            for comment_line in comment_block:
                lowered = comment_line.lower()
                if lowered.startswith("required"):
                    required = True
                elif lowered.startswith(("optional", "recommended")):
                    required = False
            keys.append(KeyInfo(name=name, description=description, required=required))
    return keys


def key_status(env_path: Path | None = None, example_path: Path | None = None) -> list[dict]:
    """Presence-only status for every known key. Never returns a value."""
    if env_path is None:
        env_path = ENV_PATH
    values = _load_dotenv(env_path)
    return [
        {
            "name": key.name,
            "description": key.description,
            "required": key.required,
            "is_set": _is_real_value(values.get(key.name, "")),
        }
        for key in known_keys(example_path)
    ]


def _is_real_value(value: str) -> bool:
    value = value.strip()
    return bool(value) and value != PLACEHOLDER_VALUE


def set_key(
    name: str,
    value: str,
    env_path: Path | None = None,
    example_path: Path | None = None,
) -> None:
    """Write/update `name` in .env, preserving all other content.

    Raises ValueError for any name not in the known registry, so this can
    never be used to write an arbitrary env var.
    """
    if env_path is None:
        env_path = ENV_PATH
    if example_path is None:
        example_path = ENV_EXAMPLE_PATH
    valid_names = {key.name for key in known_keys(example_path)}
    if name not in valid_names:
        raise UnknownKeyError(f"unknown key: {name!r}")

    value = value.strip()
    if not value:
        raise InvalidKeyValueError("key value must not be empty")
    if "\n" in value or "\r" in value or "\0" in value:
        raise InvalidKeyValueError("key value must be a single text line")
    if len(value) > MAX_KEY_VALUE_LENGTH:
        raise InvalidKeyValueError(f"key value exceeds {MAX_KEY_VALUE_LENGTH} characters")
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    elif example_path.exists():
        lines = example_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    replaced = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith(f"{name}=") or line == name:
            lines[i] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{env_path.name}.", dir=env_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # This repository deliberately uses a mode-0600 local .env as its
            # credential store; values are never logged or returned.
            # codeql[py/clear-text-storage-sensitive-data]
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(env_path)
    finally:
        tmp_path.unlink(missing_ok=True)
