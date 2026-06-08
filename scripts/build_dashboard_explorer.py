"""Build the static dashboard explorer (Gate ``dashboard``, item ``dashboard_app``).

A single self-contained HTML file that lets an analyst browse the top-form
deliverables with no server and no network: the analyst-reports catalog, the
source-provenance lineage, and a gap-matrix status summary are embedded as
inline JSON and rendered by a few lines of vanilla JavaScript (no external CSS
or JS dependencies).

Deterministic by construction — there is no timestamp or volatile value in the
HTML body (provenance time lives only in the side manifest), so the file
snapshots and reproduces byte-for-byte.

Inputs (committed, built earlier in the same run):
  exports/reports/analyst_reports_manifest.json
  exports/reports/source_drilldown.json
  reports/top_form_gap_matrix.csv
Output: ``exports/dashboard/index.html`` + ``data/manifests/dashboard_explorer.json``

CLI::

    python scripts/build_dashboard_explorer.py            # write the HTML + manifest
    python scripts/build_dashboard_explorer.py --check     # validate without writing
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[1]

ANALYST_REPORTS = "exports/reports/analyst_reports_manifest.json"
SOURCE_DRILLDOWN = "exports/reports/source_drilldown.json"
GAP_MATRIX = "reports/top_form_gap_matrix.csv"
OUT = "exports/dashboard/index.html"
MANIFEST_OUT = "data/manifests/dashboard_explorer.json"

# Markers a valid render must contain (also asserted by the test).
REQUIRED_MARKERS = (
    "Contract Sweeper",
    'id="reports"',
    'id="lineage"',
    'id="gaps"',
    'id="letters"',
    "application/json",
)


def _read_json(root: Path, rel: str) -> Any:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _gap_summary(root: Path) -> dict[str, Any]:
    """Deterministic status summary from the committed gap matrix."""
    status_counts: dict[str, int] = {}
    gate_totals: dict[str, dict[str, int]] = {}
    with (root / GAP_MATRIX).open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            st = (r.get("status") or "").strip()
            gate = (r.get("gate") or "").strip()
            status_counts[st] = status_counts.get(st, 0) + 1
            g = gate_totals.setdefault(gate, {"done": 0, "total": 0})
            g["total"] += 1
            if st == "done":
                g["done"] += 1
    return {
        "status_counts": {k: status_counts[k] for k in sorted(status_counts)},
        "gates": {k: gate_totals[k] for k in sorted(gate_totals)},
    }


def build_data(root: Path | None = None) -> dict[str, Any]:
    """Assemble the deterministic data payload embedded in the page."""
    root = root or REPO_ROOT
    reports = _read_json(root, ANALYST_REPORTS).get("reports", [])
    lineage = _read_json(root, SOURCE_DRILLDOWN).get("sources", [])
    letters = [r for r in reports if r.get("gate") == "foia" and r.get("format") == "md"]
    return {
        "title": "Contract Sweeper — Top-Form Explorer",
        "reports": reports,
        "lineage": lineage,
        "gap_summary": _gap_summary(root),
        "letters": letters,
    }


def build_html(root: Path | None = None) -> str:
    """Return the self-contained explorer HTML (deterministic)."""
    root = root or REPO_ROOT
    data = build_data(root)
    embedded = json.dumps(data, indent=2, sort_keys=True)
    # The embedded JSON is escaped so it cannot terminate the script element.
    embedded_safe = embedded.replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", embedded_safe)


def check(html: str, root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    problems: list[str] = []
    if not html.strip():
        problems.append("empty dashboard HTML")
    for marker in REQUIRED_MARKERS:
        if marker not in html:
            problems.append(f"missing marker {marker!r} in dashboard HTML")
    # the embedded JSON payload must parse
    try:
        start = html.index('id="data">') + len('id="data">')
        end = html.index("</script>", start)
        json.loads(html[start:end].replace("<\\/", "</"))
    except (ValueError, json.JSONDecodeError) as exc:
        problems.append(f"embedded JSON payload does not parse: {exc}")
    return problems


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the dashboard HTML + provenance manifest."""
    root = root or REPO_ROOT
    html = build_html(root)
    problems = check(html, root)
    if problems:
        raise ValueError("dashboard_explorer check failed: " + "; ".join(problems))
    out_path = root / OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    data = build_data(root)
    manifest = {
        "producer_script": "scripts/build_dashboard_explorer.py",
        "producer_phase": "TOP_FORM_DASHBOARD_EXPLORER",
        "source_inputs": [ANALYST_REPORTS, SOURCE_DRILLDOWN, GAP_MATRIX],
        "output": OUT,
        "report_count": len(data["reports"]),
        "lineage_count": len(data["lineage"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contract Sweeper — Top-Form Explorer</title>
<style>
  body { font: 14px/1.5 system-ui, sans-serif; margin: 0; color: #1b1f24; background: #f6f8fa; }
  header { background: #0b3d63; color: #fff; padding: 16px 24px; }
  header h1 { margin: 0; font-size: 18px; }
  nav { display: flex; gap: 4px; padding: 0 24px; background: #0b3d63; }
  nav button { background: #14507f; color: #fff; border: 0; padding: 8px 16px; cursor: pointer; font-size: 13px; }
  nav button.active { background: #f6f8fa; color: #0b3d63; font-weight: 600; }
  main { padding: 20px 24px; }
  table { border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.08); }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e1e4e8; vertical-align: top; }
  th { background: #eef2f6; position: sticky; top: 0; }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
  .done { background: #d6f5dd; color: #0a6b2b; }
  .blocked, .missing, .manual_required, .auth_required { background: #fde2e1; color: #9b1c17; }
  .partial, .unknown { background: #fff3cd; color: #8a6d00; }
  .muted { color: #6a737d; font-size: 12px; }
  section { display: none; }
  section.active { display: block; }
</style>
</head>
<body>
<header><h1>Contract Sweeper — Top-Form Explorer</h1>
<div class="muted">Static, self-contained. All data embedded below; no network required.</div></header>
<nav>
  <button data-tab="reports" class="active">Reports</button>
  <button data-tab="lineage">Lineage</button>
  <button data-tab="gaps">Gap Matrix</button>
  <button data-tab="letters">FOIA Letters</button>
</nav>
<main>
  <section id="reports" class="active"></section>
  <section id="lineage"></section>
  <section id="gaps"></section>
  <section id="letters"></section>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
  var DATA = JSON.parse(document.getElementById("data").textContent);
  function el(tag, html) { var e = document.createElement(tag); if (html != null) e.innerHTML = html; return e; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>]/g, function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c];}); }
  function table(cols, rows, cell) {
    var t = el("table"), thead = el("thead"), tr = el("tr");
    cols.forEach(function(c){ tr.appendChild(el("th", esc(c))); });
    thead.appendChild(tr); t.appendChild(thead);
    var tb = el("tbody");
    rows.forEach(function(r){ tb.appendChild(cell(r)); });
    t.appendChild(tb); return t;
  }
  function pill(s){ return '<span class="pill ' + esc(s) + '">' + esc(s) + '</span>'; }

  // Reports tab
  (function(){
    var rows = DATA.reports || [];
    var t = table(["Gate","Title","Format","Rows","Status","Path"], rows, function(r){
      var tr = el("tr");
      tr.appendChild(el("td", esc(r.gate)));
      tr.appendChild(el("td", esc(r.title)));
      tr.appendChild(el("td", esc(r.format)));
      tr.appendChild(el("td", esc(r.row_count)));
      tr.appendChild(el("td", pill(r.status)));
      tr.appendChild(el("td", '<span class="muted">' + esc(r.path) + '</span>'));
      return tr;
    });
    document.getElementById("reports").appendChild(t);
  })();

  // Lineage tab
  (function(){
    var rows = DATA.lineage || [];
    var t = table(["Artifact","Producer","Phase","Source inputs"], rows, function(r){
      var tr = el("tr");
      tr.appendChild(el("td", esc(r.artifact)));
      tr.appendChild(el("td", '<span class="muted">' + esc(r.producer_script) + '</span>'));
      tr.appendChild(el("td", esc(r.phase_label)));
      tr.appendChild(el("td", '<span class="muted">' + esc((r.source_inputs||[]).join(", ")) + '</span>'));
      return tr;
    });
    document.getElementById("lineage").appendChild(t);
  })();

  // Gap matrix tab
  (function(){
    var gs = DATA.gap_summary || {status_counts:{}, gates:{}};
    var s = document.getElementById("gaps");
    s.appendChild(el("h3", "Status counts"));
    var sc = Object.keys(gs.status_counts).map(function(k){ return {status:k, count:gs.status_counts[k]}; });
    s.appendChild(table(["Status","Count"], sc, function(r){
      var tr = el("tr"); tr.appendChild(el("td", pill(r.status))); tr.appendChild(el("td", esc(r.count))); return tr;
    }));
    s.appendChild(el("h3", "Per-gate completion"));
    var gr = Object.keys(gs.gates).map(function(k){ return {gate:k, done:gs.gates[k].done, total:gs.gates[k].total}; });
    s.appendChild(table(["Gate","Done","Total"], gr, function(r){
      var tr = el("tr"); tr.appendChild(el("td", esc(r.gate)));
      tr.appendChild(el("td", esc(r.done))); tr.appendChild(el("td", esc(r.total))); return tr;
    }));
  })();

  // FOIA Letters tab
  (function(){
    var rows = DATA.letters || [];
    var s = document.getElementById("letters");
    s.appendChild(el("h3", "FOIA / Public-Records Request Letters"));
    s.appendChild(el("p", '<span class="muted">Per-target populated request letters. To submit: fill requester info in data/reference/foia_requester.json, then run scripts/validate_foia_submission_ready.py.</span>'));
    var t = table(["Title","Status","Path"], rows, function(r){
      var tr = el("tr");
      tr.appendChild(el("td", esc(r.title)));
      tr.appendChild(el("td", pill(r.status)));
      tr.appendChild(el("td", '<span class="muted">' + esc(r.path) + '</span>'));
      return tr;
    });
    s.appendChild(t);
  })();

  // Tabs
  var buttons = document.querySelectorAll("nav button");
  buttons.forEach(function(b){
    b.addEventListener("click", function(){
      buttons.forEach(function(x){ x.classList.remove("active"); });
      b.classList.add("active");
      document.querySelectorAll("main section").forEach(function(sec){ sec.classList.remove("active"); });
      document.getElementById(b.getAttribute("data-tab")).classList.add("active");
    });
  });
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static dashboard explorer.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        html = build_html(root)
        problems = check(html, root)
        print(json.dumps({"ok": not problems, "bytes": len(html), "problems": problems}, indent=2))
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
