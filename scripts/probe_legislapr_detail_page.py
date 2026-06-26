#!/usr/bin/env python3
"""Compatibility wrapper for the canonical LegislaPR detail probe.

The implementation lives in scripts/probe_legislapr_detail.py so the source
registry, tests, and operator docs share one ingestion path.
"""

from __future__ import annotations

from scripts.probe_legislapr_detail import main


if __name__ == "__main__":
    raise SystemExit(main())
