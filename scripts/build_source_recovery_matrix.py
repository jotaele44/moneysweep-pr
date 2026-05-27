"""Source recovery matrix builder.

Reads the existing ``reports/source_registry_status.csv`` produced by
``scripts/gap_analysis_builder.py`` and classifies every source into one
of eight failure buckets, emitting both a per-source CSV and a roll-up
markdown summary under ``reports/``.

Read-only triage: no network, no writes outside ``reports/``, no edits
to the registry. Re-running yields byte-identical output.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_CSV = REPO_ROOT / "reports" / "source_registry_status.csv"
OUT_CSV = REPO_ROOT / "reports" / "source_recovery_matrix.csv"
OUT_MD = REPO_ROOT / "reports" / "source_recovery_matrix.md"

ADAPTER_REGISTRY_AFTER_PR = {
    "usaspending_prime", "usaspending_subawards", "usaspending_grants_gov",
    "grants_gov",
    "fema_pa_openfema_v2", "fema_hmgp", "nfip_claims",
    "fec", "nih_reporter", "sbir", "lda", "research_grants",
    "epa_grants", "dot_grants", "ed_grants", "hhs_grants",
    "doe_grants", "doj_grants", "usda_grants", "oia_grants",
    "slfrf", "haf", "exim_bank",
    "fdic", "nonprofits_irs990",
    "sba_ppp", "sba_loans",
    # Batch 6 (auth-gated geographic adapters)
    "opencorporates", "highergov_supplemental",
    # Entity-mode adapters
    "sam_entities", "ofac_sdn",
    # Batch 7a CMS family (Socrata + CKAN-metastore)
    "medicare_advantage", "medicare_parts",
    "cms_open_payments", "medicaid_fmap", "chip",
}

SEMANTIC_DUPLICATES = {
    "fpds_report_builder": "usaspending_prime",
    "fsrs_subawards": "usaspending_subawards",
    "congressional_earmarks": "usaspending_grants_gov",
}

HTML_PDF_OR_PR_GOV = {
    "compras_pr", "aafaf", "hacienda", "cofina", "prepa_luma_genera",
    "cor3", "prasa", "p3_authority", "oficina_contralor",
    "pr_act_60_decrees", "promesa_creditors", "rum_cover_over",
    "municipal_finance", "pr_pensions", "eqb_epa_icis",
    "pr_cabilderos", "donaciones_pr", "follow_the_money",
    "emma_bonds", "msrb_rtrs_trades",
}

ACTION_BY_BUCKET = {
    "public_api_adapter_ready":
        "Query via `python -m contract_sweeper.query --source <id>`; bulk producer unblocked by validation, not adapter work.",
    "auth_or_key_gated":
        "Set the required credential env var in `.env`; rerun producer.",
    "manual_export_only":
        "External delivery to `data/manual_import_dropzone/<family>/`; see SOURCE_RECOVERY_RUNBOOK.",
    "html_pdf_or_pr_gov_custom":
        "Defer; needs scraping adapter design pass.",
    "semantic_duplicate":
        "No action; covered by sibling source.",
    "stub_or_broken_producer":
        "Repair producer or mark stubbed in registry.",
    "required_missing_blocker":
        "Escalate; required source has no available path.",
    "never_run_or_unverified":
        "Run producer to determine bucket.",
}


def _outputs_present(expected_outputs: str) -> tuple[int, int]:
    paths = [p.strip() for p in (expected_outputs or "").split(";") if p.strip()]
    present = sum(1 for p in paths if (REPO_ROOT / p).exists())
    return len(paths), present


def _bucket(row: dict, producer_exists: bool) -> tuple[str, str]:
    sid = row["source_id"]
    auth = (row.get("authentication") or "").strip()
    required = row.get("required") == "True"
    notes = (row.get("blocker_notes") or "").lower()
    expected_outputs = row.get("expected_outputs") or ""
    _, present = _outputs_present(expected_outputs)

    if sid in ADAPTER_REGISTRY_AFTER_PR:
        return "public_api_adapter_ready", ""
    if sid in SEMANTIC_DUPLICATES:
        return "semantic_duplicate", f"covered by {SEMANTIC_DUPLICATES[sid]}"
    if not producer_exists or "stub" in notes or "broken" in notes:
        return "stub_or_broken_producer", "producer script missing or marked stub"
    if auth == "manual_export":
        return "manual_export_only", "manual delivery required"
    if auth.startswith("api_key:") or auth.startswith("oauth"):
        return "auth_or_key_gated", auth
    if sid in HTML_PDF_OR_PR_GOV:
        return "html_pdf_or_pr_gov_custom", "scrape / PDF / custom PR-gov surface"
    if required and present == 0:
        return "required_missing_blocker", "required source has no current path"
    return "never_run_or_unverified", "producer wired but not validated"


def main() -> None:
    if not STATUS_CSV.exists():
        raise SystemExit(f"missing {STATUS_CSV} — run scripts/gap_analysis_builder.py first")

    with STATUS_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    bucket_counts: Counter = Counter()
    for row in rows:
        producer = (row.get("producer_script") or "").strip()
        producer_exists = bool(producer) and (REPO_ROOT / producer).exists()
        total, present = _outputs_present(row.get("expected_outputs", ""))
        bucket, blocker = _bucket(row, producer_exists)
        bucket_counts[bucket] += 1
        out_rows.append({
            "source_id": row["source_id"],
            "required": row.get("required", ""),
            "producer_script": producer,
            "expected_outputs_count": total,
            "outputs_present_count": present,
            "failure_bucket": bucket,
            "blocker": blocker,
            "recommended_action": ACTION_BY_BUCKET[bucket],
        })

    out_rows.sort(key=lambda r: (r["failure_bucket"], r["source_id"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        for r in out_rows:
            writer.writerow(r)

    lines: list[str] = []
    lines.append("# Source Recovery Matrix")
    lines.append("")
    lines.append(f"Total sources: **{len(out_rows)}**")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| failure_bucket | count | recommended_action |")
    lines.append("| --- | --- | --- |")
    for bucket in sorted(bucket_counts, key=lambda b: (-bucket_counts[b], b)):
        lines.append(f"| `{bucket}` | {bucket_counts[bucket]} | {ACTION_BY_BUCKET[bucket]} |")
    lines.append("")
    for bucket in sorted(bucket_counts):
        members = sorted(r["source_id"] for r in out_rows if r["failure_bucket"] == bucket)
        lines.append(f"## {bucket} ({len(members)})")
        lines.append("")
        for m in members:
            lines.append(f"- `{m}`")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_CSV.relative_to(REPO_ROOT)} ({len(out_rows)} rows)")
    print(f"wrote {OUT_MD.relative_to(REPO_ROOT)}")
    for b, n in bucket_counts.most_common():
        print(f"  {b}: {n}")


if __name__ == "__main__":
    main()
