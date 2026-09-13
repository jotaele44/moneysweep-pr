#!/usr/bin/env python3
"""Fail when the authoritative status metadata is stale or points at another HEAD."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATUS_PATH = Path("reports/current_status.json")


def validate_status(
    payload: dict,
    head_sha: str,
    *,
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    errors: list[str] = []
    if payload.get("main_sha") != head_sha:
        errors.append(f"main_sha does not match HEAD ({head_sha})")
    try:
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        errors.append("generated_at is missing or invalid")
    else:
        if generated_at.tzinfo is None:
            errors.append("generated_at must include a timezone")
        elif now.astimezone(timezone.utc) - generated_at.astimezone(timezone.utc) > max_age:
            errors.append(f"generated_at is older than {max_age.days} days")
    if payload.get("evidence_snapshot_state") not in {"CURRENT", "STALE_NOT_RECERTIFIED"}:
        errors.append("evidence_snapshot_state must explicitly declare evidence freshness")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, default=STATUS_PATH)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--max-age-days", type=int, default=30)
    args = parser.parse_args(argv)
    payload = json.loads((args.repo_root / args.status).read_text(encoding="utf-8"))
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.repo_root, text=True
    ).strip()
    errors = validate_status(
        payload,
        head_sha,
        now=datetime.now(timezone.utc),
        max_age=timedelta(days=args.max_age_days),
    )
    for error in errors:
        print(f"status-freshness: {error}")
    if errors:
        return 1
    print(f"PASS status-freshness head={head_sha} state={payload['evidence_snapshot_state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
