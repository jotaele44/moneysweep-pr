#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os

PROVIDERS = {
    "FR24": ["FR24_CONFIGURED", "FR24_API_TOKEN"],
    "ADSBX": ["ADSBX_CONFIGURED", "ADSBX_API_KEY"],
    "FLIGHTAWARE": ["FLIGHTAWARE_CONFIGURED", "FLIGHTAWARE_API_KEY"],
    "OPENSKY": ["OPENSKY_CONFIGURED", "OPENSKY_CLIENT_ID"],
}


def truthy(v):
    return str(v or "").strip().lower() in {"1", "true", "yes", "configured", "present"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--require-no-secret-output", action="store_true")
    args = ap.parse_args()
    report = {}
    for provider, names in PROVIDERS.items():
        flag = truthy(os.getenv(names[0]))
        direct = bool(os.getenv(names[1]))
        report[provider] = {
            "configured": bool(flag or direct),
            "discovery_source": "boolean_flag"
            if flag
            else ("environment_presence" if direct else "none"),
            "secret_value_exposed": False,
        }
    payload = {"state": "PASS", "providers": report}
    rendered = json.dumps(payload, sort_keys=True)
    if args.require_no_secret_output:
        for name in [
            "FR24_API_TOKEN",
            "ADSBX_API_KEY",
            "FLIGHTAWARE_API_KEY",
            "OPENSKY_CLIENT_SECRET",
        ]:
            secret = os.getenv(name)
            if secret and secret in rendered:
                raise SystemExit(f"secret leak detected for {name}")
    print(rendered)


if __name__ == "__main__":
    main()
