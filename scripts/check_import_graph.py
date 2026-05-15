"""Check that no active code imports from the archived pipeline layer.

Scans all .py files under contract_sweeper/, scripts/, and tests/ for any
`from contract_sweeper.pipeline` or `import contract_sweeper.pipeline` statement.
Files under archive/ are excluded (they are inert by definition).

Exits 0 if no violations found; exits 1 and prints offending lines otherwise.
Writes data/manifests/import_graph_report.json with scan results.

Usage:
  python scripts/check_import_graph.py --root .
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCAN_DIRS = ("contract_sweeper", "scripts", "tests")
PATTERN = re.compile(r"^\s*(from|import)\s+contract_sweeper\.pipeline")
# Exclude intra-pipeline imports (whole layer archives together) and archive/ dir.
EXCLUDE_PREFIXES = ("archive", "contract_sweeper/pipeline")
# Known exceptions: CI-wired wrappers that will be removed when the
# production-status-gate.yml workflow is updated to call modules directly.
KNOWN_EXCEPTIONS = frozenset({
    "scripts/run_repo_quality_audit_r49z_b.py",
})


def scan(root: Path) -> list[dict]:
    violations: list[dict] = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.py")):
            rel = f.relative_to(root)
            if any(str(rel).startswith(p) for p in EXCLUDE_PREFIXES):
                continue
            try:
                lines = f.read_text(errors="replace").splitlines()
            except Exception:
                continue
            for lineno, line in enumerate(lines, 1):
                if PATTERN.search(line):
                    entry = {
                        "file": str(rel),
                        "line": lineno,
                        "text": line.rstrip(),
                        "known_exception": str(rel) in KNOWN_EXCEPTIONS,
                    }
                    violations.append(entry)
    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description="Import graph checker")
    parser.add_argument("--root", default=".", help="Repository root path")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    violations = scan(root)

    new_violations = [v for v in violations if not v["known_exception"]]
    known_violations = [v for v in violations if v["known_exception"]]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scan_dirs": list(SCAN_DIRS),
        "exclude_prefixes": list(EXCLUDE_PREFIXES),
        "known_exceptions": list(KNOWN_EXCEPTIONS),
        "total_violations": len(violations),
        "new_violations": len(new_violations),
        "known_violations": len(known_violations),
        "passed": len(new_violations) == 0,
        "violations": violations,
    }

    out = root / "data" / "manifests" / "import_graph_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if known_violations:
        print(f"  (known exceptions: {len(known_violations)} — "
              f"{', '.join(v['file'] for v in known_violations)})")

    if new_violations:
        print(f"FAIL: {len(new_violations)} unexpected import(s) of "
              f"contract_sweeper.pipeline found:")
        for v in new_violations:
            print(f"  {v['file']}:{v['line']}: {v['text']}")
        sys.exit(1)
    else:
        print(f"PASS: 0 unexpected imports of contract_sweeper.pipeline "
              f"(scanned {', '.join(SCAN_DIRS)})")
        sys.exit(0)


if __name__ == "__main__":
    main()
