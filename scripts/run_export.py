"""One-command federation export: map masters -> package -> validate.

Chains the three producer stages:

1. ``build_export_streams.build_streams`` — canonical masters -> 5 JSONL streams
   (written to an ephemeral staging dir).
2. ``build_export_package.build_package`` — package the streams + write manifest.
3. ``validate_export.validate_package`` — fail-closed validation in the chosen
   mode (default ``production``).

Standalone entry point; does not touch ``run_all.py`` or any pipeline stage.

Run::

    python scripts/run_export.py --processed-dir data/staging/processed
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_export_streams import DEFAULT_PROCESSED_DIR, build_streams
from scripts.build_export_package import DEFAULT_PRODUCER_VERSION, build_package
from scripts.validate_export import validate_package


def run(
    processed_dir: str | Path,
    output_dir: str | Path | None = None,
    mode: str = "production",
    generated_at: str | None = None,
    producer_version: str = DEFAULT_PRODUCER_VERSION,
) -> int:
    if output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = REPO_ROOT / "exports" / f"export_{stamp}"
    output_dir = Path(output_dir)

    with tempfile.TemporaryDirectory(prefix="cs_export_streams_") as tmp:
        staging = Path(tmp) / "streams"
        report = build_streams(processed_dir, staging, generated_at=generated_at)
        build_package(
            input_dir=staging,
            output_dir=output_dir,
            mode=mode,
            producer_version=producer_version,
        )
        errors = validate_package(output_dir, mode=mode)

    print(json.dumps({"export_streams_report": report}, indent=2, sort_keys=True))
    if errors:
        for err in errors:
            print(err.format())
        print(f"[FAIL] {len(errors)} validation error(s); package at {output_dir}")
        return 1
    print(f"[OK] export package valid in mode={mode}: {output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and validate a federation export package.")
    parser.add_argument("--processed-dir", default=str(DEFAULT_PROCESSED_DIR))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--mode", choices=("test", "production"), default="production")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--producer-version", default=DEFAULT_PRODUCER_VERSION)
    args = parser.parse_args(argv)
    return run(
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        mode=args.mode,
        generated_at=args.generated_at,
        producer_version=args.producer_version,
    )


if __name__ == "__main__":
    sys.exit(main())
