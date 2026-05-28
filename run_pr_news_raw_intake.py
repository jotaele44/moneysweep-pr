#!/usr/bin/env python3
"""Root-level runner for the PR News raw intake producer."""

from __future__ import annotations

from scripts.produce_pr_news_raw_intake import main


if __name__ == "__main__":
    raise SystemExit(main())
