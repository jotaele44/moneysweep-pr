from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from tools.check_npm_audit import evaluate, main

TODAY = dt.date(2026, 10, 7)


def _report(*advisories: tuple[str, str, str]) -> dict:
    vulns = {}
    for ghsa, package, severity in advisories:
        vulns[package] = {
            "severity": severity,
            "via": [
                {
                    "name": package,
                    "severity": severity,
                    "title": "t",
                    "url": f"https://github.com/advisories/{ghsa}",
                }
            ],
        }
        vulns[f"dep-of-{package}"] = {"severity": severity, "via": [package]}
    return {"vulnerabilities": vulns}


def _allow(tmp_path: Path, *entries: dict) -> Path:
    path = tmp_path / "allow.json"
    path.write_text(json.dumps({"advisories": list(entries)}), encoding="utf-8")
    return path


def _entry(
    ident: str = "GHSA-aaaa", expires: str = "2027-01-01", reason: str = "build only"
) -> dict:
    return {"id": ident, "package": "pkg", "reason": reason, "expires": expires}


def test_allowlisted_advisory_passes(tmp_path):
    failures, notes = evaluate(
        _report(("GHSA-aaaa", "pkg", "high")), _allow(tmp_path, _entry()), "moderate", TODAY
    )
    assert failures == []
    assert any("allowed GHSA-aaaa" in n for n in notes)


def test_new_advisory_fails(tmp_path):
    report = _report(("GHSA-aaaa", "pkg", "high"), ("GHSA-new", "other", "moderate"))
    failures, _ = evaluate(report, _allow(tmp_path, _entry()), "moderate", TODAY)
    assert [f.split()[0] for f in failures] == ["GHSA-new"]


def test_expired_entry_fails(tmp_path):
    allow = _allow(tmp_path, _entry(expires="2026-10-06"))
    failures, _ = evaluate(_report(("GHSA-aaaa", "pkg", "high")), allow, "moderate", TODAY)
    assert any("expired" in f for f in failures)
    assert any(f.startswith("GHSA-aaaa") for f in failures)


def test_entry_without_reason_is_rejected(tmp_path):
    allow = _allow(tmp_path, _entry(reason="  "))
    failures, _ = evaluate(_report(("GHSA-aaaa", "pkg", "high")), allow, "moderate", TODAY)
    assert any("needs an id and a reason" in f for f in failures)


def test_below_threshold_is_ignored(tmp_path):
    failures, _ = evaluate(_report(("GHSA-low", "pkg", "low")), _allow(tmp_path), "moderate", TODAY)
    assert failures == []


def test_stale_entry_is_noted(tmp_path):
    _, notes = evaluate({"vulnerabilities": {}}, _allow(tmp_path, _entry()), "moderate", TODAY)
    assert any("no longer reported" in n for n in notes)


def test_non_json_output_fails_closed(tmp_path):
    report = tmp_path / "r.json"
    report.write_text("not json", encoding="utf-8")
    assert main(["--report", str(report), "--allowlist", str(_allow(tmp_path))]) == 2


def test_npm_error_payload_fails_closed(tmp_path):
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"error": {"code": "ENOTFOUND"}}), encoding="utf-8")
    assert main(["--report", str(report), "--allowlist", str(_allow(tmp_path))]) == 2


def test_committed_allowlist_is_valid_and_unexpired():
    path = Path(__file__).resolve().parents[1] / "dashboard" / "audit-allowlist.json"
    from tools.check_npm_audit import load_allowlist

    allowed, problems = load_allowlist(path, dt.date.today())
    assert problems == []
    assert allowed
