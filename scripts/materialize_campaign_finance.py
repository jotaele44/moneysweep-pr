"""Run MoneySweep's complete, fail-closed campaign-finance materialization ladder."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging


def _run_step(name: str, fn, results: dict, **kwargs):
    try:
        results[name] = fn(**kwargs)
    except Exception as exc:  # preserve the rest of the ladder and certify failure
        results[name] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


def run(
    root: Path | None = None,
    *,
    live_oce: bool = False,
    live_fec: bool = False,
    skip_fec_outflows: bool = False,
    strict: bool = False,
) -> dict:
    root = Path(root) if root is not None else PROJECT_ROOT
    logger = setup_logging("materialize_campaign_finance")
    results: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "options": {
            "live_oce": live_oce,
            "live_fec": live_fec,
            "skip_fec_outflows": skip_fec_outflows,
            "strict": strict,
        },
    }

    from scripts import ingest_donaciones, ingest_fec, ingest_oce

    # Offline/operator-delivered inputs first.
    fec_raw = root / "data" / "raw" / "FEC"
    if fec_raw.exists() and any(fec_raw.glob("*.csv")):
        _run_step("fec_ingest", ingest_fec.run, results, root=root, force=True)
    elif (root / "data" / "staging" / "processed" / "pr_fec_contributions.csv").exists():
        results["fec_ingest"] = {"status": "EXISTING_PROCESSED_OUTPUT"}
    else:
        results["fec_ingest"] = {"status": "NO_INPUT"}

    _run_step("cee_ingest", ingest_donaciones.run, results, root=root, force=True)
    _run_step("oce_ingest", ingest_oce.run, results, root=root, force=True)

    if live_oce:
        from scripts import download_oce

        _run_step("oce_live", download_oce.run, results, root=root, force=True)

    if live_fec:
        from scripts import download_fec, download_fec_committees

        _run_step("fec_live", download_fec.run, results, root=root, force=True)
        _run_step(
            "fec_committees_live",
            download_fec_committees.run,
            results,
            root=root,
            force=True,
            skip_disbursements=skip_fec_outflows,
            skip_expenditures=skip_fec_outflows,
        )
    elif not os.environ.get("FEC_API_KEY"):
        results["fec_live"] = {"status": "SKIPPED_NO_FEC_API_KEY"}

    # Certification path: normalized names may discover candidates but may
    # never promote identity or canonical graph endpoints by themselves.
    from scripts import build_campaign_finance_entities_certified

    _run_step(
        "entity_resolution",
        build_campaign_finance_entities_certified.run,
        results,
        root=root,
    )

    # Derived crossrefs are conditional on their own upstreams.
    try:
        from scripts import analyze_political_crossref

        _run_step(
            "fec_awards_crossref", analyze_political_crossref.build_fec_crossref, results, root=root
        )
        _run_step(
            "ngo_donation_crossref",
            analyze_political_crossref.build_ngo_donation_crossref,
            results,
            root=root,
        )
    except Exception as exc:
        results["crossrefs"] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

    from scripts import validate_campaign_finance_materialization_certified

    validation = validate_campaign_finance_materialization_certified.run(root=root, strict=strict)
    results["validation"] = validation
    # A stale-but-valid file on disk must not mask a failed ladder step: any
    # recorded step ERROR blocks the overall result alongside file validation.
    step_errors = sorted(
        name
        for name, value in results.items()
        if isinstance(value, dict) and value.get("status") == "ERROR"
    )
    if step_errors:
        results["step_errors"] = step_errors
    results["status"] = "OK" if validation["ok"] and not step_errors else "INCOMPLETE"

    out_dir = root / "data" / "manifests" / "campaign_finance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "materialization_run_latest.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    results["manifest_path"] = str(out_path)
    logger.info(f"Campaign-finance ladder: {results['status']} → {out_path}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-oce", action="store_true")
    parser.add_argument("--live-fec", action="store_true")
    parser.add_argument("--skip-fec-outflows", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = run(
        live_oce=args.live_oce,
        live_fec=args.live_fec,
        skip_fec_outflows=args.skip_fec_outflows,
        strict=args.strict,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "OK" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
