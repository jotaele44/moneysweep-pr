"""Audit how much data is materialized vs. the publicly available universe.

Two layers, intentionally separable so the offline answer never depends on the
network:

1. **Source-level (offline, always runs).** For every registered source,
   classify the *local working-tree* materialization of its declared
   ``expected_outputs``. This reuses
   :func:`scripts.gap_analysis_builder._file_status` /
   :func:`~scripts.gap_analysis_builder._source_status`, so the status logic is
   byte-identical to the committed gap analysis. The only difference is *where*
   it runs: against the local tree (where the gitignored
   ``data/staging/processed/pr_*.csv`` masters exist), not a clean/CI checkout
   (where they don't — which is why every committed report reads 0%).

2. **Record-universe (network, ``--probe``).** For the high-value sources where
   we hold authentic bulk data, fetch the authoritative *PR-scoped* total from
   the source's public, **keyless** API and compute
   ``coverage = local_rows / universe_total``. Filters mirror the producers
   (place-of-performance = PR) so numerator and denominator are apples-to-apples.
   Key-gated sources (FEC/SAM/HigherGov/OpenCorporates) and sources without a
   keyless count endpoint stay documented estimates, clearly labelled.

Writes (never touches the committed CI-view reports):
  reports/materialization_coverage_audit.json
  reports/materialization_coverage_audit.csv

Usage:
  python3 scripts/audit_materialization_coverage.py            # offline only
  python3 scripts/audit_materialization_coverage.py --probe    # + live universe probes
  python3 scripts/audit_materialization_coverage.py --root /path/to/repo
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

from scripts.gap_analysis_builder import _file_status, _source_status  # reuse status logic
from contract_sweeper.runtime.source_registry import load_source_registry
from contract_sweeper.runtime.base_downloader import (
    HttpConfig,
    build_session,
    http_get_json,
    http_post_json,
)

# ---------------------------------------------------------------------------
# Materiality tiers — purely a function of how many real rows are on disk.
# These describe *what kind* of artifact a source has, independent of whether
# all declared outputs are present (that is the gap-style `local_status`).
# ---------------------------------------------------------------------------
TIER_BULK = "bulk"  # >= 1000 rows  — substantive downloaded universe
TIER_MODERATE = "moderate"  # 50..999 rows  — real but partial / small source
TIER_SEED_STUB = "seed_stub"  # 1..49 rows    — seed / static / placeholder
TIER_EMPTY = "empty"  # 0 rows / header-only / absent


def _materiality_tier(local_rows: int) -> str:
    if local_rows >= 1000:
        return TIER_BULK
    if local_rows >= 50:
        return TIER_MODERATE
    if local_rows >= 1:
        return TIER_SEED_STUB
    return TIER_EMPTY


PROCESSED_SUBDIR = "data/staging/processed"


def _csv_row_count(path: Path) -> int:
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:  # noqa: BLE001
        return -1


# Non-terminal pipeline intermediates: produced and consumed internally (the
# normalized_expansion_* FPDS/DoD/reconstruction shards and the SAM-enrichment
# vendor_targets.csv are folded into pr_contracts_master.csv by
# deduplicate_master.py / sam_enrichment.py). They are real rows on disk but not
# primary source outputs, so they classify as "intermediate", not "orphan".
INTERMEDIATE_PREFIXES = ("normalized_expansion_",)
INTERMEDIATE_NAMES = frozenset({"vendor_targets.csv"})


def _is_intermediate(name: str) -> bool:
    return name in INTERMEDIATE_NAMES or any(name.startswith(p) for p in INTERMEDIATE_PREFIXES)


def inventory_processed_files(root: Path) -> dict[str, Any]:
    """Inventory every materialized CSV in data/staging/processed and classify it.

    Surfaces the *registry-drift* gap: real data on disk that no registry source
    claims via ``expected_outputs`` (orphans) — e.g. the 461k-row
    ``pr_grants_master.csv`` declared by no source, or path-mismatched files like
    ``pr_ofac_sdn.csv`` (registry expects ``ofac_sdn.csv``). Such rows are real
    but structurally invisible to the registry-driven accounting, even locally.
    """
    declared_names: dict[str, list[str]] = {}
    for s in load_source_registry(root).get("sources", []):
        for o in s.get("expected_outputs", []) or []:
            declared_names.setdefault(Path(o).name, []).append(s["source_id"])

    proc = root / PROCESSED_SUBDIR
    files: list[dict[str, Any]] = []
    total_rows = declared_rows = orphan_rows = intermediate_rows = 0
    for p in sorted(proc.glob("*.csv")):
        rc = _csv_row_count(p)
        rows = max(rc, 0)
        claimed_by = declared_names.get(p.name, [])
        is_intermediate = _is_intermediate(p.name)
        is_orphan = not claimed_by and not is_intermediate and rows >= 1
        total_rows += rows
        if claimed_by:
            declared_rows += rows
            classification = "declared"
        elif is_intermediate and rows >= 1:
            intermediate_rows += rows
            classification = "intermediate"
        elif is_orphan:
            orphan_rows += rows
            classification = "orphan"
        else:
            classification = "empty"
        files.append(
            {
                "file": p.name,
                "rows": rows,
                "claimed_by": ";".join(claimed_by),
                "classification": classification,
            }
        )
    files.sort(key=lambda r: -r["rows"])
    return {
        "processed_dir": PROCESSED_SUBDIR,
        "total_csv_files": len(files),
        "total_rows_on_disk": total_rows,
        "registry_accounted_rows": declared_rows,
        "orphan_rows": orphan_rows,
        "orphan_file_count": sum(1 for f in files if f["classification"] == "orphan"),
        "intermediate_rows": intermediate_rows,
        "intermediate_file_count": sum(1 for f in files if f["classification"] == "intermediate"),
        "files": files,
    }


# ---------------------------------------------------------------------------
# Layer 1 — offline local-tree coverage
# ---------------------------------------------------------------------------
def compute_local_coverage(root: Path) -> dict[str, Any]:
    """Per-source local materialization, computed against the working tree."""
    sources = load_source_registry(root).get("sources", [])
    records: list[dict[str, Any]] = []
    summary: dict[str, float] = {
        "total_sources": 0,
        "required_sources": 0,
        "fully_materialized": 0,
        "partially_materialized": 0,
        "not_materialized": 0,
        "no_outputs_declared": 0,
        "required_fully_materialized": 0,
        "tier_bulk": 0,
        "tier_moderate": 0,
        "tier_seed_stub": 0,
        "tier_empty": 0,
        "total_local_rows": 0,
    }

    for src in sources:
        sid = src.get("source_id", "")
        required = bool(src.get("required", False))
        expected = src.get("expected_outputs", []) or []
        file_statuses = [{**_file_status(root, rel), "path": rel} for rel in expected]
        present = [f for f in file_statuses if f["status"] == "present"]
        local_rows = sum(f["row_count"] for f in present if f["row_count"] > 0)
        status = _source_status(root, src)
        tier = _materiality_tier(local_rows)

        summary["total_sources"] += 1
        summary["required_sources"] += int(required)
        summary["total_local_rows"] += local_rows
        if status in summary:
            summary[status] += 1
        if status == "fully_materialized" and required:
            summary["required_fully_materialized"] += 1
        summary[f"tier_{tier}"] += 1

        records.append(
            {
                "source_id": sid,
                "family": src.get("family", ""),
                "required": required,
                "authentication": src.get("authentication", ""),
                "expected_output_count": len(expected),
                "present_count": len(present),
                "local_rows": local_rows,
                "min_rows_threshold": src.get("validation_threshold", {}).get("min_rows", 1),
                "local_status": status,
                "materiality_tier": tier,
                "first_expected_output": expected[0] if expected else "",
            }
        )

    records.sort(key=lambda r: (-r["local_rows"], r["source_id"]))
    summary["coverage_rate_fully"] = (
        round(summary["fully_materialized"] / summary["total_sources"], 4)
        if summary["total_sources"]
        else 0.0
    )
    summary["materialized_any_data"] = (
        summary["tier_bulk"] + summary["tier_moderate"] + summary["tier_seed_stub"]
    )
    return {"summary": summary, "sources": records}


# ---------------------------------------------------------------------------
# Layer 2 — live universe probes (keyless public APIs only)
# ---------------------------------------------------------------------------
USASPENDING_COUNT_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"
FEMA_BASE_V2 = "https://www.fema.gov/api/open/v2/"
LDA_FILINGS_URL = "https://lda.senate.gov/api/v1/filings/"

PR_POP = [{"country": "USA", "state": "PR"}]
# 2007-10-01 is USAspending's earliest searchable date for spending_by_award
# (the API returns 422 for earlier starts; pre-2008 needs the bulk-download
# feature). This is also the repo producers' earliest window, so numerator and
# denominator share the same lower bound.
FULL_WINDOW = [{"start_date": "2007-10-01", "end_date": "2026-09-30"}]

# Quiet, count-only HTTP: no inter-page sleep, no long rate-limit naps.
_PROBE_HTTP = HttpConfig(page_sleep=0.0, rate_limit_sleep=5.0, max_retries=3)


def _logger():
    import logging

    lg = logging.getLogger("audit_probe")
    if not lg.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    return lg


def probe_usaspending_prime(session, logger) -> dict[str, Any]:
    """One call to spending_by_award_count → per-category PR prime award counts."""
    payload = {
        "filters": {
            "time_period": FULL_WINDOW,
            "place_of_performance_locations": PR_POP,
        }
    }
    data = http_post_json(
        session, USASPENDING_COUNT_URL, payload, logger=logger, config=_PROBE_HTTP
    )
    if not data or "results" not in data:
        return {"status": "error", "detail": "no results from count endpoint"}
    r = data["results"]
    return {
        "status": "ok",
        "endpoint": USASPENDING_COUNT_URL,
        "scope": "place_of_performance=PR, FY2008-2026 (award-level)",
        "counts": r,
        # contracts master folds prime contracts + IDVs (+ historical FPDS)
        "contracts_universe": int(r.get("contracts", 0)) + int(r.get("idvs", 0)),
        # grants master is broad assistance at finer granularity than award-level
        # "grants" (23k). The comparable award universe is all assistance types.
        "grants_only_universe": int(r.get("grants", 0)),
        "assistance_universe": (
            int(r.get("grants", 0))
            + int(r.get("direct_payments", 0))
            + int(r.get("loans", 0))
            + int(r.get("other", 0))
        ),
    }


def probe_fema_pa(session, logger) -> dict[str, Any]:
    """PR Public Assistance project-detail universe: PR disaster numbers → count.

    Mirrors download_openfema_pa_projects.py: PR disaster numbers from
    DisasterDeclarationsSummaries, then count PublicAssistanceFundedProjectsDetails
    for those disasters (batched, summing metadata.count).
    """

    def _get(url: str) -> dict | None:
        return http_get_json(session, url, {}, logger=logger, config=_PROBE_HTTP)

    # 1) PR disaster numbers (mirror the producer: no $select — FEMA errors on it)
    nums: set[int] = set()
    skip = 0
    while True:
        url = (
            f"{FEMA_BASE_V2}DisasterDeclarationsSummaries"
            f"?$filter=state eq 'PR'&$inlinecount=allpages&$top=1000&$skip={skip}"
        )
        data = _get(url)
        if not data:
            break
        page = data.get("DisasterDeclarationsSummaries", [])
        if not page:
            break
        nums.update(int(r["disasterNumber"]) for r in page if r.get("disasterNumber"))
        total = (data.get("metadata") or {}).get("count")
        skip += 1000
        if total and skip >= total:
            break
    if not nums:
        return {"status": "error", "detail": "no PR disaster numbers"}

    # 2) Count project details for those disasters (batched like the producer)
    ordered = sorted(nums)
    batch_size = 15
    total_details = 0
    for i in range(0, len(ordered), batch_size):
        batch = ordered[i : i + batch_size]
        or_clause = " or ".join(f"disasterNumber eq {n}" for n in batch)
        url = (
            f"{FEMA_BASE_V2}PublicAssistanceFundedProjectsDetails"
            f"?$inlinecount=allpages&$top=1&$filter={or_clause}"
        )
        data = _get(url)
        if not data:
            continue
        total_details += int((data.get("metadata") or {}).get("count", 0))
    return {
        "status": "ok",
        "endpoint": FEMA_BASE_V2 + "PublicAssistanceFundedProjectsDetails",
        "scope": f"{len(nums)} PR disaster numbers",
        "universe": total_details,
    }


def probe_lda(session, logger) -> dict[str, Any]:
    """Federal LDA filings with a PR-domiciled client (DRF `count`)."""
    url = f"{LDA_FILINGS_URL}?filing_year=&client_state=PR&page_size=1"
    data = http_get_json(session, url, {}, logger=logger, config=_PROBE_HTTP)
    if not data or "count" not in data:
        return {"status": "error", "detail": "no count from LDA filings"}
    return {
        "status": "ok",
        "endpoint": LDA_FILINGS_URL,
        "scope": "client_state=PR, all years",
        "universe": int(data["count"]),
    }


def _coverage_pct(local: int, universe: int | None) -> float | None:
    if not universe:
        return None
    return round(100.0 * local / universe, 2)


def _parsed_count(path: Path, fy_ge: int | None = None) -> tuple[int, int]:
    """(matching_records, total_records) via a real CSV parse.

    Line-counting overcounts CSVs whose text fields contain embedded newlines
    (e.g. award descriptions in pr_grants_master.csv: ~462k lines but ~377k
    records). For coverage numerators we need *records*, optionally restricted to
    fiscal_year >= ``fy_ge`` so the numerator's date window matches the API
    denominator. Returns (0, 0) if the file is unreadable.
    """
    import pandas as pd

    try:
        if fy_ge is not None:
            fy = pd.to_numeric(
                pd.read_csv(path, usecols=["fiscal_year"], low_memory=False)["fiscal_year"],
                errors="coerce",
            )
            return int((fy >= fy_ge).sum()), int(len(fy))
        n = int(len(pd.read_csv(path, usecols=[0], low_memory=False)))
        return n, n
    except Exception:  # noqa: BLE001
        return 0, 0


def run_universe_probes(
    root: Path, local: dict[str, Any], inventory: dict[str, Any]
) -> list[dict[str, Any]]:
    """Probe keyless universes and join to local row counts. Failure-tolerant."""
    logger = _logger()
    session = build_session()
    by_id = {s["source_id"]: s for s in local["sources"]}
    disk_by_file = {f["file"]: f["rows"] for f in inventory["files"]}
    proc = root / PROCESSED_SUBDIR

    def rows(*ids: str) -> int:
        return sum(by_id.get(i, {}).get("local_rows", 0) for i in ids)

    def disk_rows(basename: str) -> int:
        """Actual rows on disk for a file, even if no source declares it (orphan)."""
        return disk_by_file.get(basename, 0)

    results: list[dict[str, Any]] = []

    # --- USAspending prime: split contracts vs grants ---------------------
    try:
        us = probe_usaspending_prime(session, logger)
    except Exception as exc:  # noqa: BLE001 — probe must never crash the audit
        us = {"status": "error", "detail": repr(exc)}
    if us.get("status") == "ok":
        # Numerator must match the API's FY2008+ window: count only FY>=2008 rows
        # (the master also folds ~1.4k pre-2008 FPDS rows the denominator excludes).
        c_fy2008, c_total = _parsed_count(proc / "pr_contracts_master.csv", fy_ge=2008)
        c_univ = us["contracts_universe"]
        crow = _uni_row(
            "usaspending_prime",
            "contracts (+IDVs), FY2008+",
            c_fy2008,
            c_univ,
            "USAspending spending_by_award_count",
            us["scope"],
            note=(
                f"numerator = FY2008+ records only; master also holds "
                f"{c_total - c_fy2008:,} pre-2008 FPDS rows outside the API window "
                f"(total master records = {c_total:,})"
            ),
        )
        results.append(crow)
        # grants master (pr_grants_master.csv) is an ORPHAN — declared by no
        # source. It is broad assistance (mostly loans + direct payments; true
        # grants are a small minority), so compare to ALL assistance awards.
        # Use the PARSED record count (line-count overcounts ~462k vs ~377k due
        # to embedded newlines in descriptions).
        g_records, _ = _parsed_count(proc / "pr_grants_master.csv")
        grow = _uni_row(
            "usaspending_prime_grants",
            "all assistance (grants+dp+loans+other)",
            g_records,
            us["assistance_universe"],
            "USAspending spending_by_award_count",
            us["scope"],
            note=(
                "orphan file pr_grants_master.csv (no registry source); APPROXIMATE — "
                "numerator is parsed records (line-count inflates to "
                f"{disk_rows('pr_grants_master.csv'):,}); award-level grants-only "
                f"universe = {us['grants_only_universe']:,}"
            ),
        )
        grow["method"] = "live_probe_approx"
        grow["universe_breakdown"] = us["counts"]
        results.append(grow)
    else:
        results.append(_uni_error("usaspending_prime", us.get("detail", "")))

    # --- USAspending subawards: no keyless count endpoint -----------------
    results.append(
        {
            "source_id": "usaspending_subawards",
            "label": "subawards",
            "local_rows": rows("usaspending_subawards"),
            "universe_total": None,
            "coverage_pct": None,
            "method": "estimate",
            "scope": "no keyless count endpoint (spending_by_award_count is prime-only)",
            "note": "denominator requires paginating spending_by_award subawards=true",
        }
    )

    # --- FEMA PA ----------------------------------------------------------
    try:
        fema = probe_fema_pa(session, logger)
    except Exception as exc:  # noqa: BLE001
        fema = {"status": "error", "detail": repr(exc)}
    if fema.get("status") == "ok":
        results.append(
            _uni_row(
                "fema_pa_openfema_v2",
                "PA project details",
                rows("fema_pa_openfema_v2"),
                fema["universe"],
                "OpenFEMA $inlinecount",
                fema["scope"],
            )
        )
    else:
        results.append(_uni_error("fema_pa_openfema_v2", fema.get("detail", "")))

    # --- LDA --------------------------------------------------------------
    try:
        lda = probe_lda(session, logger)
    except Exception as exc:  # noqa: BLE001
        lda = {"status": "error", "detail": repr(exc)}
    if lda.get("status") == "ok":
        results.append(
            _uni_row(
                "lda",
                "federal lobbying filings",
                rows("lda"),
                lda["universe"],
                "lda.senate.gov filings count",
                lda["scope"],
            )
        )
    else:
        results.append(_uni_error("lda", lda.get("detail", "")))

    # --- Key-gated / no-keyless-count: documented estimates ---------------
    # local_rows read from disk so orphan/path-mismatched files still count
    # (e.g. fec -> pr_fec_contributions.csv, ofac -> pr_ofac_sdn.csv).
    for sid, label, disk_file, note in [
        (
            "fec",
            "campaign contributions",
            "pr_fec_contributions.csv",
            "key-gated (FEC_API_KEY); denominator is an estimate",
        ),
        (
            "sam_entities",
            "registered entities",
            "",
            "key-gated (SAM_API_KEY); not materialized locally",
        ),
        (
            "emma_bonds",
            "municipal bond issues",
            "pr_emma_bonds.csv",
            "EMMA has no keyless count API",
        ),
        (
            "ofac_sdn",
            "SDN list (global, not PR-scoped)",
            "pr_ofac_sdn.csv",
            "reference list; we hold the full feed (orphan path: pr_ofac_sdn.csv)",
        ),
    ]:
        results.append(
            {
                "source_id": sid,
                "label": label,
                "local_rows": disk_rows(disk_file) if disk_file else rows(sid),
                "universe_total": None,
                "coverage_pct": None,
                "method": "estimate",
                "scope": note,
                "note": "",
            }
        )

    session.close()
    return results


def _uni_row(sid, label, local_rows, universe, method, scope, note=""):
    return {
        "source_id": sid,
        "label": label,
        "local_rows": local_rows,
        "universe_total": universe,
        "coverage_pct": _coverage_pct(local_rows, universe),
        "method": "live_probe",
        "scope": scope,
        "endpoint_method": method,
        "note": note,
    }


def _uni_error(sid, detail):
    return {
        "source_id": sid,
        "label": "",
        "local_rows": None,
        "universe_total": None,
        "coverage_pct": None,
        "method": "probe_failed",
        "scope": "",
        "note": detail,
    }


# ---------------------------------------------------------------------------
# Committed CI-view contrast (read-only)
# ---------------------------------------------------------------------------
def read_committed_ci_view(root: Path) -> dict[str, Any]:
    """Load the committed gap report (clean-checkout view) for the contrast."""
    p = root / "reports" / "gap_analysis_report.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {
            "source": "reports/gap_analysis_report.json",
            "generated_at": d.get("generated_at"),
            "fully_materialized": d.get("fully_materialized"),
            "partially_materialized": d.get("partially_materialized"),
            "coverage_rate": d.get("coverage_rate"),
            "note": "reflects a clean/CI checkout where gitignored "
            "data/staging/processed/pr_*.csv masters are absent",
        }
    except Exception as exc:  # noqa: BLE001
        return {"source": str(p), "error": repr(exc)}


# ---------------------------------------------------------------------------
# Orchestration / output
# ---------------------------------------------------------------------------
def build_audit(root: Path, probe: bool) -> dict[str, Any]:
    local = compute_local_coverage(root)
    inventory = inventory_processed_files(root)
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "coverage_audit_v1",
        "root": str(root),
        "committed_ci_view": read_committed_ci_view(root),
        "local_truth_summary": local["summary"],
        "processed_file_inventory": inventory,
        "sources": local["sources"],
        "universe_coverage": run_universe_probes(root, local, inventory) if probe else [],
        "probe_ran": probe,
    }
    return result


def write_outputs(root: Path, audit: dict[str, Any]) -> tuple[Path, Path]:
    out_dir = root / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "materialization_coverage_audit.json"
    json_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")

    csv_path = out_dir / "materialization_coverage_audit.csv"
    fields = [
        "source_id",
        "family",
        "required",
        "authentication",
        "expected_output_count",
        "present_count",
        "local_rows",
        "local_status",
        "materiality_tier",
        "first_expected_output",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(audit["sources"])

    # File-level inventory (declared vs orphan) — the registry-drift evidence.
    files_csv = out_dir / "materialization_coverage_audit_files.csv"
    with files_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["file", "rows", "classification", "claimed_by"], extrasaction="ignore"
        )
        w.writeheader()
        w.writerows(audit["processed_file_inventory"]["files"])
    return json_path, csv_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    p.add_argument(
        "--probe",
        action="store_true",
        help="Make read-only calls to keyless public APIs for universe totals.",
    )
    a = p.parse_args(argv)
    root = Path(a.root).resolve()
    audit = build_audit(root, probe=a.probe)
    json_path, csv_path = write_outputs(root, audit)
    s = audit["local_truth_summary"]
    ci = audit["committed_ci_view"]
    inv = audit["processed_file_inventory"]
    print(
        json.dumps(
            {
                "committed_ci_fully_materialized": ci.get("fully_materialized"),
                "local_fully_materialized": s["fully_materialized"],
                "local_partially_materialized": s["partially_materialized"],
                "local_sources_with_any_data": s["materialized_any_data"],
                "total_sources": s["total_sources"],
                "registry_accounted_local_rows": s["total_local_rows"],
                "total_rows_on_disk": inv["total_rows_on_disk"],
                "orphan_rows_not_in_registry": inv["orphan_rows"],
                "orphan_file_count": inv["orphan_file_count"],
                "probe_ran": audit["probe_ran"],
                "outputs": [str(json_path), str(csv_path)],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
