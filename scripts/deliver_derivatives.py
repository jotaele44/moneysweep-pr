#!/usr/bin/env python3
"""Deliver a routed derivative CSV into a sibling repo's intake dropzone.

This is the *logic* underneath the cross-repo intake-delivery automation: given
the router's export directory and a target dropzone path, it copies the named
derivative (default the spiderweb-pr lane file) into the dropzone, creating it if
needed. The GitHub Actions workflow (`.github/workflows/intake-delivery.yml`)
calls this and then opens the cross-repo PR — the PR step needs a
`FEDERATION_DELIVERY_TOKEN` PAT and is not exercised offline; this file is.

The copy operation is injectable so the logic is unit-testable without touching
a real sibling checkout.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SPIDERWEB_DERIVATIVE = "spiderweb_pr_derivatives.csv"
SPIDERWEB_DROPZONE = "data/intake/pr_intake"


def deliver(derivatives_dir, dropzone_dir, filename: str = SPIDERWEB_DERIVATIVE, copy=shutil.copy2) -> dict:
    """Copy ``<derivatives_dir>/<filename>`` into ``<dropzone_dir>/<filename>``.

    Returns a result dict. Raises FileNotFoundError if the source is absent.
    ``copy`` is injectable (defaults to ``shutil.copy2``) for offline testing.
    """
    src = Path(derivatives_dir) / filename
    if not src.is_file():
        raise FileNotFoundError(f"derivative not found: {src}")
    dropzone = Path(dropzone_dir)
    dropzone.mkdir(parents=True, exist_ok=True)
    dest = dropzone / filename
    copy(str(src), str(dest))
    return {"source": str(src), "dest": str(dest), "filename": filename}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derivatives-dir", required=True,
                        help="Directory holding the router's *_derivatives.csv files")
    parser.add_argument("--dropzone", required=True,
                        help="Target sibling-repo intake dropzone directory")
    parser.add_argument("--filename", default=SPIDERWEB_DERIVATIVE,
                        help=f"Derivative file to deliver (default: {SPIDERWEB_DERIVATIVE})")
    args = parser.parse_args(argv)
    try:
        result = deliver(args.derivatives_dir, args.dropzone, args.filename)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"delivered {result['filename']} -> {result['dest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
