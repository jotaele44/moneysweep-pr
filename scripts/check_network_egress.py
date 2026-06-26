#!/usr/bin/env python3
"""Check outbound HTTPS egress for moneysweep-pr materialization.

This script is intentionally non-mutating:
- no producers are executed
- no source files are downloaded
- no credentials are read or printed

Exit code:
- 0 when all checked HTTPS endpoints are reachable
- 1 when one or more checks fail
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urlparse


DEFAULT_ENDPOINTS = [
    "https://api.usaspending.gov/",
    "https://www.fsrs.gov/",
    "https://sam.gov/",
    "https://lda.senate.gov/",
    "https://api.open.fec.gov/",
    "https://www.highergov.com/",
    "https://api.gleif.org/",
    "https://data.sec.gov/",
]


@dataclass(frozen=True)
class EgressCheck:
    url: str
    host: str
    port: int
    ok: bool
    error: str = ""


def check_https_endpoint(url: str, timeout: float = 5.0) -> EgressCheck:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 443

    if parsed.scheme != "https" or not host:
        return EgressCheck(url=url, host=host, port=port, ok=False, error="invalid https url")

    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as raw_sock:
            with context.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                tls_sock.settimeout(timeout)
                tls_sock.sendall(
                    (
                        f"HEAD {parsed.path or '/'} HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        "User-Agent: moneysweep-pr-Egress-Check/1.0\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                )
                response = tls_sock.recv(64)
        if response.startswith(b"HTTP/"):
            return EgressCheck(url=url, host=host, port=port, ok=True)
        return EgressCheck(url=url, host=host, port=port, ok=False, error="no HTTP response")
    except Exception as exc:
        return EgressCheck(
            url=url,
            host=host,
            port=port,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def run_checks(endpoints: Iterable[str], timeout: float = 5.0) -> dict:
    checks = [check_https_endpoint(url, timeout=timeout) for url in endpoints]
    blocked = [check for check in checks if not check.ok]
    return {
        "ok": not blocked,
        "checked": [asdict(check) for check in checks],
        "blocked": [asdict(check) for check in blocked],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("endpoints", nargs="*", default=DEFAULT_ENDPOINTS)
    args = parser.parse_args(argv)

    result = run_checks(args.endpoints, timeout=args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["ok"]:
            print("network egress check passed")
        else:
            print("network egress check failed")
            for item in result["blocked"]:
                print(f"- {item['url']}: {item['error']}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
