"""Self-contained smoke test for the export producer.

Builds a package from ``exports/samples/`` into a throwaway temp directory and
runs the fail-closed validator against it in test mode. No network, no external
services. Exits 0 on success, 1 on any validation error.

Run::

    python scripts/smoke_export.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_export_package, validate_export


def run() -> int:
    samples_dir = REPO_ROOT / "exports" / "samples"
    with tempfile.TemporaryDirectory(prefix="cs_export_smoke_") as tmp:
        output_dir = Path(tmp) / "package"
        build_export_package.build_package(
            input_dir=samples_dir,
            output_dir=output_dir,
            mode="test",
        )
        errors = validate_export.validate_package(output_dir, mode="test")

    if errors:
        for err in errors:
            print(err.format())
        print(f"[FAIL] export smoke failed with {len(errors)} error(s)")
        return 1

    print("[OK] export smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
