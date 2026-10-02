"""Materialize Puerto Rico Foreign-Trade Zones Board zone/site records.

The discovery denominator is frozen to the three Puerto Rico zones independently
confirmed on the FTZ Board public information system: 7, 61 and 163. The numeric
OFIS detail ids are transport locators only; the producer verifies the returned
zone number before retaining anything.

When ``GUIDE_SOURCE_SNAPSHOT_DIR`` is set, exact HTTP response bytes are frozen
alongside a machine-readable manifest containing retrieval UTC, URL/transport
locator, response metadata, SHA256, byte size and retained row counts. Existing
snapshots are never overwritten because each run receives a UTC run directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from lxml import html as lxml_html

from moneysweep.runtime.base_downloader import HttpConfig, build_session, file_has_data
from moneysweep.runtime.post_ingest import apply_post_ingest
from scripts.config import PROJECT_ROOT, setup_logging

SOURCE_ID = "ftz_board_pr"
OUT_REL = "data/staging/processed/pr_ftz_zones_sites.csv"
DETAILS = {"007": 103, "061": 239, "163": 115}
BASE = "https://ofis.trade.gov/Zones/Details/{detail_id}"
COLUMNS = [
    "source_record_id",
    "record_type",
    "zone_number_raw",
    "approved_date_raw",
    "grantee_raw",
    "location_raw",
    "zone_status_raw",
    "port_of_entry_raw",
    "activation_limit_raw",
    "total_activated_acres_raw",
    "site_number_raw",
    "site_name_raw",
    "site_status_raw",
    "activated_acres_raw",
    "sunset_expiration_lapse_date_raw",
    "source_detail_id",
    "source_url",
    "retrieved_at_utc",
]

HTTP = HttpConfig(
    user_agent="Mozilla/5.0 (compatible; MoneySweep/1.0; PR public-money research)",
    max_retries=3,
    base_delay_seconds=2.0,
    max_delay_seconds=12.0,
    page_sleep=0.25,
    rate_limit_sleep=30.0,
    timeout=30,
)


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _sid(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _lines(doc) -> list[str]:
    # XPath text-node extraction preserves adjacent sibling values such as
    # <div>Zone Number</div><div>061</div>. Using text_content().splitlines()
    # can silently concatenate those siblings into "Zone Number061".
    return [cleaned for text in doc.xpath("//text()") if (cleaned := _clean(str(text)))]


def _label_value(lines: list[str], label: str) -> str:
    for i, line in enumerate(lines):
        if line == label and i + 1 < len(lines):
            return lines[i + 1]
    return ""


def _site_rows(doc) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for table in doc.xpath("//table"):
        headers = [_clean(x.text_content()) for x in table.xpath(".//thead//th")]
        if not headers:
            first = table.xpath(".//tr[1]/th|.//tr[1]/td")
            headers = [_clean(x.text_content()) for x in first]
        if "Site Number" not in headers or "Site Name" not in headers:
            continue
        body_rows = table.xpath(".//tbody/tr") or table.xpath(".//tr[position()>1]")
        for tr in body_rows:
            cells = [_clean(x.text_content()) for x in tr.xpath("./td")]
            if len(cells) < 4:
                continue
            cells += [""] * (5 - len(cells))
            rows.append(
                {
                    "site_number_raw": cells[0],
                    "site_name_raw": cells[1],
                    "site_status_raw": cells[2],
                    "activated_acres_raw": cells[3],
                    "sunset_expiration_lapse_date_raw": cells[4],
                }
            )
        break
    return rows


def parse_zone(
    page_html: str,
    *,
    detail_id: int,
    source_url: str,
    retrieved_at: str,
) -> list[dict]:
    doc = lxml_html.fromstring(page_html)
    lines = _lines(doc)
    zone = _label_value(lines, "Zone Number")
    if zone.isdigit():
        zone = zone.zfill(3)
    if not zone:
        raise RuntimeError(f"FTZ detail {detail_id}: missing Zone Number")

    base = {
        "zone_number_raw": zone,
        "approved_date_raw": _label_value(lines, "Approved on Date"),
        "grantee_raw": _label_value(lines, "Grantee"),
        "location_raw": _label_value(lines, "Location"),
        "zone_status_raw": _label_value(lines, "Status"),
        "port_of_entry_raw": _label_value(lines, "Port of Entry"),
        "activation_limit_raw": _label_value(lines, "Activation Limit"),
        "total_activated_acres_raw": _label_value(lines, "Total Activated Acres"),
        "source_detail_id": str(detail_id),
        "source_url": source_url,
        "retrieved_at_utc": retrieved_at,
    }

    output: list[dict] = []
    zone_row = {col: "" for col in COLUMNS}
    zone_row.update(base)
    zone_row["record_type"] = "zone"
    zone_row["source_record_id"] = _sid("zone", zone, str(detail_id))
    output.append(zone_row)

    for site in _site_rows(doc):
        row = {col: "" for col in COLUMNS}
        row.update(base)
        row.update(site)
        row["record_type"] = "site"
        row["source_record_id"] = _sid("site", zone, site["site_number_raw"], site["site_name_raw"])
        output.append(row)
    return output


def run(root: Path | None = None, *, force: bool = False) -> dict:
    root = root or PROJECT_ROOT
    out_path = root / OUT_REL
    if not force and file_has_data(out_path):
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        return {"rows": len(existing), "path": str(out_path), "errors": []}

    logger = setup_logging("scrape_ftz_board_pr")
    session = build_session(HTTP.user_agent, HTTP.extra_headers)
    rows: list[dict] = []
    observed: set[str] = set()
    run_started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    snapshot_base = os.getenv("GUIDE_SOURCE_SNAPSHOT_DIR", "").strip()
    snapshot_run: Path | None = None
    snapshot_entries: list[dict] = []
    if snapshot_base:
        run_token = run_started_at.replace(":", "").replace("+00:00", "Z")
        snapshot_run = Path(snapshot_base) / SOURCE_ID / run_token
        snapshot_run.mkdir(parents=True, exist_ok=False)

    try:
        for expected_zone, detail_id in DETAILS.items():
            url = BASE.format(detail_id=detail_id)
            response = session.get(url, timeout=HTTP.timeout)
            response.raise_for_status()
            retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            raw_bytes = response.content
            raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            raw_rel = ""
            if snapshot_run is not None:
                raw_name = f"zone_{expected_zone}_detail_{detail_id}.html"
                raw_path = snapshot_run / raw_name
                raw_path.write_bytes(raw_bytes)
                raw_rel = raw_name

            parsed = parse_zone(
                response.text,
                detail_id=detail_id,
                source_url=url,
                retrieved_at=retrieved_at,
            )
            actual = parsed[0]["zone_number_raw"]
            if actual != expected_zone:
                raise RuntimeError(
                    f"FTZ locator mismatch: detail_id={detail_id} "
                    f"expected={expected_zone} observed={actual}"
                )
            if actual in observed:
                raise RuntimeError(f"FTZ duplicate zone: {actual}")
            observed.add(actual)
            rows.extend(parsed)
            snapshot_entries.append(
                {
                    "expected_zone": expected_zone,
                    "observed_zone": actual,
                    "detail_id": detail_id,
                    "url": url,
                    "retrieved_at_utc": retrieved_at,
                    "http_status": response.status_code,
                    "content_type": response.headers.get("Content-Type", ""),
                    "byte_size": len(raw_bytes),
                    "sha256": raw_sha256,
                    "raw_file": raw_rel,
                    "retained_rows": len(parsed),
                }
            )
    finally:
        session.close()

    expected = set(DETAILS)
    if observed != expected:
        raise RuntimeError(
            f"FTZ denominator mismatch: expected={sorted(expected)} observed={sorted(observed)}"
        )

    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty or int((df["record_type"] == "zone").sum()) != len(expected):
        raise RuntimeError("FTZ zone arithmetic closure failed")
    if df["source_record_id"].duplicated().any():
        raise RuntimeError("FTZ duplicate source_record_id")
    if df["zone_number_raw"].isna().any() or df["zone_number_raw"].eq("").any():
        raise RuntimeError("FTZ null zone_number_raw")

    df = apply_post_ingest(df, source_id=SOURCE_ID, root=root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8")
    output_bytes = out_path.read_bytes()

    manifest_path = ""
    if snapshot_run is not None:
        manifest = {
            "schema_version": "guide_source_snapshot_manifest_v1",
            "source_id": SOURCE_ID,
            "run_started_at_utc": run_started_at,
            "source_denominator": {
                "expected_zone_numbers": sorted(expected),
                "observed_zone_numbers": sorted(observed),
                "expected_zone_count": len(expected),
                "observed_zone_count": len(observed),
            },
            "manifestations": snapshot_entries,
            "processed_output": {
                "path": OUT_REL,
                "row_count": len(df),
                "byte_size": len(output_bytes),
                "sha256": hashlib.sha256(output_bytes).hexdigest(),
            },
            "certification_scope_note": (
                "Frozen FTZ Board source manifestations establish this bounded public route only; "
                "they do not expand GUIDE_BOUNDED_100_PERCENT into ALL_PUERTO_RICO_FINANCE."
            ),
        }
        manifest_file = snapshot_run / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest_path = str(manifest_file)

    logger.info("FTZ Board PR: %s rows across %s zones", len(df), len(expected))
    return {
        "rows": len(df),
        "path": str(out_path),
        "snapshot_manifest": manifest_path,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"FTZ Board PR: {result['rows']:,} rows -> {result['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
