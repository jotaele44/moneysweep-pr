"""Financial data-source audit ledger.

Re-projects every registered source into the plain-language buckets a money-flow
audit cares about — **wired & materializing**, **wired but not working**, **not
set to materialize anything**, **queued** (manual / scraper), and **not even
considered** — with a financial-domain lens layered on top.

This is a *read-only re-projection*, not a new classifier. The path-type decision
(``api_adapter`` / ``api_producer`` / ``manual_export`` / ``scraper_needed`` /
``deferred_stub`` / ``semantic_duplicate`` / ``broken_producer``) and the
producer-health / outputs-on-disk signals are reused verbatim from
``scripts/build_source_recovery_matrix.py`` and ``scripts/pipeline_preflight.py``
so the audit can never drift from the materialization gate.

Inputs (no network):
  - the live source registry via ``load_source_registry``
  - the recovery-matrix classifier (``_classify``, ``_outputs_present``, ...)
  - per-source producer health via ``classify_source_readiness``
  - the "not considered" coverage backlog (optional ``reports/financial_source_coverage_gaps.csv``)

Outputs (under ``reports/``, deterministic / byte-identical on re-run):
  - ``financial_source_audit.csv``  — per-source audit row
  - ``financial_source_audit.md``   — narrative answering the four audit questions

Read-only triage: no network, no writes outside ``reports/``, no registry edits.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.source_registry import load_source_registry
from scripts.build_source_recovery_matrix import (
    PATH_TYPES,
    _classify,
    _outputs_present,
)
from scripts.pipeline_preflight import STRUCTURAL_STATUSES, classify_source_readiness

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = REPO_ROOT / "reports" / "financial_source_audit.csv"
OUT_MD = REPO_ROOT / "reports" / "financial_source_audit.md"

# Registry `family` -> (financial_domain, is_financial). Supporting reference
# layers (entity resolution, archival metadata, commercial enrichment) are not
# money-flow sources themselves but are kept in the ledger and flagged.
FAMILY_DOMAIN = {
    "federal": ("federal_awards", True),
    "territorial": ("territorial_spending", True),
    "municipal": ("municipal_finance", True),
    "infrastructure": ("infrastructure_contracts", True),
    "infrastructure_revenue": ("infrastructure_revenue", True),
    "bonds": ("debt_and_bonds", True),
    "political_finance": ("political_finance", True),
    "lobbying": ("lobbying_influence", True),
    "manual_export": ("manual_financial", True),
    "nonprofit": ("nonprofit_funding", True),
    "entity_resolution": ("entity_resolution", False),
    "provenance_archival": ("archival_provenance", False),
    "optional_commercial_enrichment": ("commercial_enrichment", False),
}

# Manual-export sources that can nonetheless materialize fully offline from a
# git-tracked input already in the repo (no operator file, no network). Keyed on
# the *tracked* input — not the gitignored output — so the signal reproduces in a
# clean checkout. See scripts/ingest_act_transition.py (offline fallback).
OFFLINE_SOURCE_INPUTS = {
    "act_transition_contracts": "data/raw/act_transition/transition_contracts_extracted.csv",
    "acuden_2024_transition": "data/raw/act_transition/transition_contracts_extracted.csv",
    "follow_the_money": "data/raw/follow_the_money/municipality_political_federal_bridge.csv",
}

# path_type -> the plain-language audit bucket. Automatable path types are
# resolved further by outputs-on-disk / key presence in ``_audit_status``.
PATH_TYPE_BUCKET = {
    "manual_export": "queued_manual",
    "scraper_needed": "queued_scraper",
    "deferred_stub": "wired_not_set_to_materialize",
    "semantic_duplicate": "wired_not_set_to_materialize",
    "broken_producer": "broken",
}

# Ordered for stable, readable rollups (most-wired first).
BUCKET_ORDER = [
    "wired_materializing",
    "wired_offline_ready",
    "wired_ready_unmaterialized",
    "wired_needs_key",
    "wired_not_set_to_materialize",
    "queued_manual",
    "queued_scraper",
    "broken",
    "not_considered",
]

BUCKET_BLURB = {
    "wired_materializing": "Wired and producing output on disk now.",
    "wired_offline_ready": "Wired; materializes fully offline from a committed input (no operator file/network).",
    "wired_ready_unmaterialized": "Wired and ready; just needs a run (network egress).",
    "wired_needs_key": "Wired and automatable, but its API key is not set.",
    "wired_not_set_to_materialize": "Wired but produces nothing by design (deferred stub / sibling duplicate).",
    "queued_manual": "Wired, but waits on an operator-delivered manual export.",
    "queued_scraper": "Declared, but needs a scraping adapter for a PR-gov HTML/PDF surface.",
    "broken": "Producer is missing / fails import / has no callable entrypoint.",
    "not_considered": "Real-world financial source with no registry entry yet.",
}

# Verb prefixes stripped from a producer filename stem before aligning it to a
# source_id. e.g. scripts/download_act60.py -> "act60".
PRODUCER_VERB_PREFIXES = ("download_", "ingest_", "build_", "extract_", "fetch_")


def _producer_basename(producer_script: str) -> str:
    return Path(producer_script).name if producer_script else ""


def _producer_stem(producer_script: str) -> str:
    stem = Path(producer_script).stem if producer_script else ""
    for prefix in PRODUCER_VERB_PREFIXES:
        if stem.startswith(prefix):
            return stem[len(prefix) :]
    return stem


def _name_aligned(source_id: str, producer_script: str) -> bool:
    """Heuristic: does the producer filename obviously map to the source_id?

    Aggregators / shared producers (build_unified_master, ngo_integration, ...)
    legitimately serve differently-named sources; this flags only the cases where
    a source's identity is *not* recoverable from its producer name, which is the
    registry-enumeration risk we want surfaced — not a defect by itself.
    """
    if not source_id or not producer_script:
        return False
    sid = source_id.lower()
    stem = _producer_stem(producer_script).lower()
    if not stem:
        return False
    return stem in sid or sid in stem


def _audit_status(source_id: str, path_type: str, readiness: str, present: int) -> str:
    bucket = PATH_TYPE_BUCKET.get(path_type)
    if bucket:
        # A queued manual source with a committed offline input is better than queued.
        if bucket == "queued_manual" and _offline_input(source_id):
            return "wired_offline_ready"
        return bucket
    # Automatable (api_adapter / api_producer): resolve by output / key state.
    if present > 0:
        return "wired_materializing"
    if readiness == "missing_key_limited":
        return "wired_needs_key"
    return "wired_ready_unmaterialized"


def _offline_input(source_id: str) -> str:
    """Return the tracked offline input path for a source, or '' if none exists."""
    rel = OFFLINE_SOURCE_INPUTS.get(source_id)
    if rel and (REPO_ROOT / rel).exists():
        return rel
    return ""


def _blocker(audit_status: str, needs_key: str, dropzone: str) -> str:
    if audit_status == "wired_materializing":
        return ""
    if audit_status == "wired_offline_ready":
        return "run producer to materialize from committed input"
    if audit_status == "wired_ready_unmaterialized":
        return "needs a producer run (network egress)"
    if audit_status == "wired_needs_key":
        return f"API key {needs_key} not set"
    if audit_status == "wired_not_set_to_materialize":
        return "no output by design"
    if audit_status == "queued_manual":
        return f"awaiting operator file in {dropzone}" if dropzone else "awaiting operator file"
    if audit_status == "queued_scraper":
        return "needs scraping adapter"
    if audit_status == "broken":
        return "producer defect"
    return ""


def build_rows() -> list[dict]:
    sources = load_source_registry(REPO_ROOT).get("sources", [])
    rows: list[dict] = []
    for src in sources:
        sid = src.get("source_id", "")
        family = src.get("family", "")
        auth = (src.get("authentication") or "").strip()
        producer = src.get("producer_script", "") or ""
        expected = list(src.get("expected_outputs") or [])
        total, present = _outputs_present(expected)
        path_type = _classify(src)
        readiness = classify_source_readiness(REPO_ROOT, src)["readiness_status"]
        audit_status = _audit_status(sid, path_type, readiness, present)
        needs_key = auth.split("api_key:", 1)[1] if auth.startswith("api_key:") else ""
        dropzone = src.get("manual_drop_dir", "") or ""
        domain, is_financial = FAMILY_DOMAIN.get(family, ("uncategorized", True))
        rows.append(
            {
                "source_id": sid,
                "audit_status": audit_status,
                "is_financial": is_financial,
                "financial_domain": domain,
                "family": family,
                "required": bool(src.get("required", False)),
                "path_type": path_type,
                "automatable": PATH_TYPES[path_type][0],
                "producer_importable": readiness not in STRUCTURAL_STATUSES,
                "needs_key": needs_key,
                "producer_script": producer,
                "producer_basename": _producer_basename(producer),
                "producer_name_aligned": _name_aligned(sid, producer),
                "expected_outputs_count": total,
                "outputs_present_count": present,
                "offline_input": _offline_input(sid),
                "blocker": _blocker(audit_status, needs_key, dropzone),
                "recommended_action": PATH_TYPES[path_type][1],
            }
        )

    rows.extend(_coverage_gap_rows())
    rows.sort(
        key=lambda r: (
            BUCKET_ORDER.index(r["audit_status"]),
            not r["is_financial"],
            r["financial_domain"],
            r["source_id"],
        )
    )
    return rows


def _coverage_gap_rows() -> list[dict]:
    """`not_considered` rows from the Workstream-3 coverage backlog, if present.

    Sourced from ``reports/financial_source_coverage_gaps.csv`` when it exists
    (columns: source_id, financial_domain, blocker, recommended_action). Absent
    that file the audit still builds — the bucket is simply empty.
    """
    gap_csv = REPO_ROOT / "reports" / "financial_source_coverage_gaps.csv"
    if not gap_csv.exists():
        return []
    out: list[dict] = []
    with gap_csv.open(encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f):
            out.append(
                {
                    "source_id": rec.get("source_id", ""),
                    "audit_status": "not_considered",
                    "is_financial": True,
                    "financial_domain": rec.get("financial_domain", "uncategorized"),
                    "family": "",
                    "required": False,
                    "path_type": "",
                    "automatable": False,
                    "producer_importable": False,
                    "needs_key": "",
                    "producer_script": "",
                    "producer_basename": "",
                    "producer_name_aligned": False,
                    "expected_outputs_count": 0,
                    "outputs_present_count": 0,
                    "offline_input": "",
                    "blocker": rec.get("blocker", "no registry entry"),
                    "recommended_action": rec.get(
                        "recommended_action", "evaluate for registry intake"
                    ),
                }
            )
    return out


def _write_csv(rows: list[dict]) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _md_table(header: list[str], body: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(cells) + " |" for cells in body)
    return lines


def _write_md(rows: list[dict]) -> None:
    registry_rows = [r for r in rows if r["audit_status"] != "not_considered"]
    financial = [r for r in registry_rows if r["is_financial"]]
    supporting = [r for r in registry_rows if not r["is_financial"]]
    bucket_counts = Counter(r["audit_status"] for r in rows)
    fin_bucket = Counter(r["audit_status"] for r in financial)

    lines = ["# Financial Data-Source Audit", ""]
    lines.append(
        f"Registry sources: **{len(registry_rows)}** "
        f"(financial: **{len(financial)}**, supporting/reference: **{len(supporting)}**). "
        f"Not-yet-considered candidates: **{bucket_counts.get('not_considered', 0)}**."
    )
    lines.append("")
    lines.append(
        "_Read-only re-projection of `reports/source_recovery_matrix.csv` + live producer "
        "health into money-flow audit buckets. Regenerate with "
        "`python3 scripts/build_financial_source_audit.py`._"
    )
    lines.append("")

    lines.append("## Status buckets (all sources)")
    lines.append("")
    body = [
        [f"`{b}`", str(bucket_counts.get(b, 0)), str(fin_bucket.get(b, 0)), BUCKET_BLURB[b]]
        for b in BUCKET_ORDER
    ]
    lines += _md_table(["audit_status", "all", "financial", "meaning"], body)
    lines.append("")

    lines.append("## The four questions")
    lines.append("")
    wired_now = fin_bucket.get("wired_materializing", 0)
    offline_ready = fin_bucket.get("wired_offline_ready", 0)
    wired_ready = fin_bucket.get("wired_ready_unmaterialized", 0) + fin_bucket.get(
        "wired_needs_key", 0
    )
    not_mat = fin_bucket.get("wired_not_set_to_materialize", 0)
    queued = fin_bucket.get("queued_manual", 0) + fin_bucket.get("queued_scraper", 0)
    broken = fin_bucket.get("broken", 0)
    not_considered = bucket_counts.get("not_considered", 0)
    lines.append(
        f"1. **Which financial sources are wired?** {wired_now + offline_ready + wired_ready + queued} "
        f"are wired to a producer — {wired_now} producing output now, {offline_ready} able to "
        f"materialize fully offline from committed inputs, {wired_ready} automatable & ready to run "
        f"(incl. key-gated), {queued} wired but queued behind a manual export or scraper."
    )
    lines.append(
        f"2. **Which don't work?** {broken} have a structural producer defect "
        "(missing / import error / no entrypoint). Runtime correctness beyond import is not "
        "verified offline — see caveat below."
    )
    lines.append(
        f"3. **Which aren't set to materialize anything?** {not_mat} produce nothing by design "
        "(deferred stubs + semantic duplicates of sibling sources)."
    )
    lines.append(
        f"4. **Which haven't even been considered?** {not_considered} real-world financial sources "
        "have no registry entry (see `financial_source_coverage_gaps.md`)."
    )
    lines.append("")
    lines.append(
        "> **Caveat:** `producer_importable` is a static import/entrypoint check — it does **not** "
        "confirm a producer yields valid rows at run time. With outbound egress blocked in this "
        "environment, live-API correctness is unverified; only offline-materializable sources are "
        "proven end-to-end."
    )
    lines.append("")

    lines.append("## Financial domains")
    lines.append("")
    by_domain: dict[str, Counter] = defaultdict(Counter)
    for r in financial:
        by_domain[r["financial_domain"]]["total"] += 1
        by_domain[r["financial_domain"]][r["audit_status"]] += 1
    dbody = [
        [
            f"`{dom}`",
            str(by_domain[dom]["total"]),
            str(by_domain[dom].get("wired_materializing", 0)),
            str(by_domain[dom].get("queued_manual", 0) + by_domain[dom].get("queued_scraper", 0)),
        ]
        for dom in sorted(by_domain)
    ]
    lines += _md_table(["financial_domain", "sources", "materializing", "queued"], dbody)
    lines.append("")

    misaligned = [
        r for r in registry_rows if not r["producer_name_aligned"] and r["producer_basename"]
    ]
    lines.append(f"## Producer/source-id name mismatches ({len(misaligned)})")
    lines.append("")
    lines.append(
        "Sources whose `source_id` is not recoverable from the producer filename. Legitimate for "
        "shared aggregators, but a registry-enumeration risk worth tracking (a rename or audit "
        "keyed on filenames can silently miss these)."
    )
    lines.append("")
    mbody = [
        [f"`{r['source_id']}`", f"`{r['producer_basename']}`", r["financial_domain"]]
        for r in sorted(misaligned, key=lambda r: r["source_id"])
    ]
    lines += _md_table(["source_id", "producer", "financial_domain"], mbody)
    lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows = build_rows()
    _write_csv(rows)
    _write_md(rows)
    counts = Counter(r["audit_status"] for r in rows)
    print(f"wrote {OUT_CSV.relative_to(REPO_ROOT)} ({len(rows)} rows)")
    print(f"wrote {OUT_MD.relative_to(REPO_ROOT)}")
    for b in BUCKET_ORDER:
        print(f"  {b:30} {counts.get(b, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
