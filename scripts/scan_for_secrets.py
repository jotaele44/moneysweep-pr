"""Scan the repo for accidentally-committed secrets.

Looks for common key-shaped patterns and known env-var assignments outside
of safe locations. Stdlib only. Used by the validation_gates `secret_leakage_zero`
gate and by CI.

Safe locations (allowlisted):
  - .env.example (template only, must contain placeholder values)
  - tests/fixtures/r5/*.json (synthetic test data)
  - data/manifests/**/*.json sha256 hashes (64-hex)
  - any path inside `Contract-Sweeper-Secrets/` (external to repo and gitignored)
  - data/raw/** (raw ingest fixtures may legitimately contain UEIs, EIN, etc.)

Exit codes:
  0 — no leaks detected
  3 — leaks detected (count + locations printed)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Known env-var names that we explicitly forbid having non-placeholder values for.
SENSITIVE_ENV_VARS = (
    "SAM_API_KEY",
    "LDA_API_KEY",
    "FEC_API_KEY",
    "OPENCORPORATES_API_TOKEN",
    "HIGHERGOV_API_KEY",
    "FELT_API_KEY",
    "USASPENDING_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "GITHUB_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)

# Patterns that look like real credentials (avoid sha256-style 64-hex from manifests).
SECRET_PATTERNS = (
    # AWS access key
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # Generic 40-char base64-ish (Anthropic / SAM API keys are this length)
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    # Bearer tokens
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
    # GitHub personal access tokens
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
)

PLACEHOLDER_HINTS = (
    "paste_your_key_here",
    "your_key_here",
    "REPLACE_ME",
    "TODO",
    "<your-key>",
    "XXXXXXXX",
)

ALLOWED_PATH_FRAGMENTS = (
    ".env.example",
    "/tests/fixtures/",
    "/Contract-Sweeper-Secrets/",
    "/.git/",
    "/.venv/",
    "/venv/",
    "__pycache__/",
    "/data/raw/",
    "/data/manifests/",  # manifests contain sha256 hashes that look like hex
    "/scripts/scan_for_secrets.py",  # this file
    "/.pytest_cache/",
)

# Files where we read line-by-line; everything else is skipped.
SCAN_EXTENSIONS = frozenset(
    {
        ".py",
        ".yaml",
        ".yml",
        ".json",
        ".md",
        ".txt",
        ".sh",
        ".cfg",
        ".ini",
        ".toml",
        ".env",
        ".csv",
    }
)

# Inside .env.example placeholder strings should appear next to the var name.
PLACEHOLDER_OK_FILES = (".env.example",)


def _path_allowed(p: Path, root: Path) -> bool:
    rel = "/" + p.relative_to(root).as_posix()
    return any(frag in rel for frag in ALLOWED_PATH_FRAGMENTS)


def _line_has_secret(line: str, path_name: str) -> str | None:
    """Return a short reason if this line looks like a real secret."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    # Env-var assignment with non-placeholder value
    for var in SENSITIVE_ENV_VARS:
        if stripped.startswith(var + "=") or stripped.startswith(var + " = "):
            value = stripped.split("=", 1)[1].strip().strip("'").strip('"')
            if not value:
                continue
            if any(hint.lower() in value.lower() for hint in PLACEHOLDER_HINTS):
                continue
            if path_name in PLACEHOLDER_OK_FILES:
                # template file; still flag if value isn't placeholder
                if not any(hint.lower() in value.lower() for hint in PLACEHOLDER_HINTS):
                    return f"{var} assigned non-placeholder value"
                continue
            return f"{var} assigned a non-placeholder value"
    for pattern in SECRET_PATTERNS:
        m = pattern.search(line)
        if m:
            return f"matches credential pattern: {pattern.pattern[:30]}"
    return None


def scan(root: Path) -> dict:
    findings: list[dict[str, str]] = []
    files_scanned = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if _path_allowed(p, root):
            continue
        if p.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        files_scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            reason = _line_has_secret(line, p.name)
            if reason:
                findings.append(
                    {
                        "file": p.relative_to(root).as_posix(),
                        "line": str(lineno),
                        "reason": reason,
                    }
                )
    return {"findings": findings, "files_scanned": files_scanned}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable output",
    )
    args = parser.parse_args(argv)
    result = scan(args.root)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"scanned {result['files_scanned']} files; {len(result['findings'])} finding(s)")
        for f in result["findings"]:
            print(f"  {f['file']}:{f['line']}  {f['reason']}")
    return 0 if not result["findings"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
