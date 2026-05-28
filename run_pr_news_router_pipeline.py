#!/usr/bin/env python3
"""Root-level runner for PR News raw-intake producer plus PR intake router."""

from __future__ import annotations

from scripts.run_pr_news_router_pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
