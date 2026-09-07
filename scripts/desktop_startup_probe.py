#!/usr/bin/env python3
"""Exercise a real local desktop API and built SPA; not a full operator journey."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.sources.append(values["src"])


def probe(app_import: str, health_path: str, timeout: float = 30) -> dict:
    import uvicorn

    if not health_path.startswith("/") or health_path.startswith("//"):
        raise ValueError("health_path must be local")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    started = datetime.now(timezone.utc).isoformat()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app_import, log_level="error", access_log=False))
    failures = []

    def serve():
        try:
            server.run(sockets=[sock])
        except BaseException as exc:
            failures.append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    class LocalRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlparse(newurl).netloc != urlparse(base).netloc or urlparse(newurl).scheme != "http":
                raise ValueError("redirect outside the local app refused")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = build_opener(ProxyHandler({}), LocalRedirects())
    requests = []

    def fetch(path):
        url = urljoin(base + "/", path)
        if urlparse(url).netloc != urlparse(base).netloc or urlparse(url).scheme != "http":
            raise ValueError("external frontend dependency requires explicit configuration")
        with opener.open(url, timeout=5) as response:
            if urlparse(response.url).netloc != urlparse(base).netloc:
                raise ValueError("redirected outside the local app")
            content = response.read()
            kind = response.headers.get_content_type()
            requests.append({"path": path, "status": response.status, "content_type": kind,
                             "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
            return content, kind

    problem = None
    try:
        deadline = time.monotonic() + timeout
        while not server.started:
            if failures or not thread.is_alive():
                raise RuntimeError(f"app startup failed: {failures}")
            if time.monotonic() >= deadline:
                raise TimeoutError("app startup timeout")
            time.sleep(0.05)
        health, kind = fetch(health_path)
        if kind != "application/json" or not isinstance(json.loads(health), dict):
            raise ValueError("health endpoint did not return a JSON object")
        page, kind = fetch("/")
        if kind != "text/html":
            raise ValueError("frontend root did not serve HTML")
        parser = ScriptSources()
        parser.feed(page.decode("utf-8"))
        if not parser.sources:
            raise ValueError("no built frontend script found")
        for source in parser.sources:
            body, kind = fetch(source)
            if not body or kind not in {"application/javascript", "text/javascript"}:
                raise ValueError("frontend script missing or shadowed by SPA fallback")
        return {"schema_version": "desktop_startup_probe.v1", "state": "PASS",
                "certification": "AUDIT_ONLY", "scope": "local API, SPA HTML and script delivery",
                "operator_journey": "UNVERIFIED", "started_utc": started,
                "completed_utc": datetime.now(timezone.utc).isoformat(), "requests": requests}
    except BaseException as exc:
        problem = exc
        raise
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        if thread.is_alive() and problem is None:
            raise RuntimeError("app failed to stop after probe")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    try:
        config = importlib.import_module("desktop.config")
        result = probe("desktop.app_server:app", getattr(config, "HEALTH_PATH", "/health"), args.timeout)
    except (Exception, SystemExit) as exc:
        result = {"schema_version": "desktop_startup_probe.v1", "state": "FAIL",
                  "certification": "AUDIT_ONLY", "error": str(exc)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(result, target, indent=2)
        target.write("\n")
    print(json.dumps(result))
    return 0 if result["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
