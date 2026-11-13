"""Frontend dependency security gate with an explicit, expiring allow-list.

Runs ``npm audit --json`` in ``dashboard/`` and fails when any advisory at or
above the chosen severity is not listed in ``dashboard/audit-allowlist.json``.
Unlike ``npm audit --audit-level``, a known advisory that has no patched release
can be tolerated, but only with a written reason and an expiry date, and every
other advisory (including new ones) still fails the build.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
ALLOWLIST = DASHBOARD / "audit-allowlist.json"
SEVERITIES = ("info", "low", "moderate", "high", "critical")


def advisory_id(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def root_advisories(report: dict) -> dict[str, dict]:
    """Advisories that npm reports directly (``via`` entries that are objects)."""
    found: dict[str, dict] = {}
    for name, vuln in (report.get("vulnerabilities") or {}).items():
        for via in vuln.get("via") or []:
            if isinstance(via, dict) and via.get("url"):
                found[advisory_id(via["url"])] = {
                    "package": via.get("name") or name,
                    "severity": via.get("severity", "high"),
                    "title": via.get("title", ""),
                }
    return found


def load_allowlist(path: Path, today: dt.date) -> tuple[dict[str, dict], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    allowed: dict[str, dict] = {}
    problems: list[str] = []
    for entry in data.get("advisories", []):
        ident = entry.get("id", "")
        if not ident or not str(entry.get("reason", "")).strip():
            problems.append(f"allow-list entry {ident or entry!r} needs an id and a reason")
            continue
        try:
            expires = dt.date.fromisoformat(entry.get("expires", ""))
        except ValueError:
            problems.append(f"{ident}: 'expires' must be an ISO date (YYYY-MM-DD)")
            continue
        if expires < today:
            problems.append(f"{ident} ({entry.get('package')}): allow-list entry expired {expires}")
            continue
        allowed[ident] = entry
    return allowed, problems


def evaluate(
    report: dict, allowlist: Path, severity: str, today: dt.date
) -> tuple[list[str], list[str]]:
    """Return (failures, notes)."""
    threshold = SEVERITIES.index(severity)
    allowed, failures = load_allowlist(allowlist, today)
    found = root_advisories(report)
    notes: list[str] = []
    for ident, info in sorted(found.items()):
        if SEVERITIES.index(info["severity"]) < threshold:
            continue
        if ident in allowed:
            notes.append(f"allowed {ident} {info['package']} ({info['severity']}): {info['title']}")
        else:
            failures.append(f"{ident} {info['package']} ({info['severity']}): {info['title']}")
    notes.extend(
        f"allow-list entry {ident} no longer reported; remove it"
        for ident in sorted(set(allowed) - set(found))
    )
    return failures, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--severity", choices=SEVERITIES, default="moderate")
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    parser.add_argument("--report", type=Path, help="use a saved `npm audit --json` file")
    args = parser.parse_args(argv)

    if args.report:
        raw = args.report.read_text(encoding="utf-8")
    else:
        # npm exits non-zero when it finds vulnerabilities; the JSON is what matters.
        proc = subprocess.run(
            ["npm", "audit", "--json"],
            cwd=DASHBOARD,
            capture_output=True,
            text=True,
            check=False,
            shell=sys.platform == "win32",
        )
        raw = proc.stdout
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        print("npm audit did not return JSON; failing closed.", file=sys.stderr)
        return 2
    if "vulnerabilities" not in report:
        print(f"npm audit reported an error: {report.get('error') or report}", file=sys.stderr)
        return 2

    failures, notes = evaluate(report, args.allowlist, args.severity, dt.date.today())
    for note in notes:
        print(f"note: {note}")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"npm audit gate passed at >={args.severity} (allow-listed advisories noted above).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
