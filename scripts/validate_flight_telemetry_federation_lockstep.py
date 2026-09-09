#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONTRACT = ROOT / ".federation" / "flight_telemetry_contract.json"
EXPECTED_SHA256 = "15d13c9c625ac1318589b3a4aae0c9f0c776e06b439a98c733d50ed90a849506"
PEERS = [
    "jotaele44/skywatcher-pr",
    "jotaele44/spiderweb-pr",
    "jotaele44/aguayluz-pr",
    "jotaele44/moneysweep-pr",
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_hashes(hashes):
    if set(hashes) != set(PEERS):
        raise SystemExit(f"peer set mismatch: {sorted(hashes)}")
    bad = {k: v for k, v in hashes.items() if v != EXPECTED_SHA256}
    if bad:
        raise SystemExit(f"lockstep hash mismatch: {bad}")


def self_test():
    good = {p: EXPECTED_SHA256 for p in PEERS}
    validate_hashes(good)
    bad = dict(good)
    bad[PEERS[-1]] = "0" * 64
    try:
        validate_hashes(bad)
    except SystemExit:
        pass
    else:
        raise SystemExit("negative lockstep regression failed")
    print(
        json.dumps(
            {"state": "PASS", "self_test": "PASS", "negative_lockstep_regression": "PASS"},
            sort_keys=True,
        )
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    ref = os.getenv("GITHUB_HEAD_REF") or os.getenv("GITHUB_REF_NAME") or "main"
    local_repo = os.getenv("GITHUB_REPOSITORY")
    local_bytes = LOCAL_CONTRACT.read_bytes()
    if sha(local_bytes) != EXPECTED_SHA256:
        raise SystemExit("local contract hash mismatch")
    hashes = {}
    for repo in PEERS:
        if repo == local_repo:
            hashes[repo] = sha(local_bytes)
            continue
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/.federation/flight_telemetry_contract.json"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = r.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SystemExit(f"BLOCKED peer contract fetch {repo}@{ref}: {type(exc).__name__}")
        hashes[repo] = sha(data)
    validate_hashes(hashes)
    print(
        json.dumps(
            {
                "state": "PASS",
                "ref": ref,
                "contract_sha256": EXPECTED_SHA256,
                "peer_count": len(PEERS),
                "strict_parallel_development": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
