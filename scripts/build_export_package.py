"""Build a Contract-Sweeper federation export package.

Reads pre-shaped JSONL stream files from ``--input-dir`` (default:
``exports/samples/``), copies them into ``--output-dir`` under canonical
names (stripping any ``.sample`` infix), computes sha256 + record counts,
and writes ``manifest.json``.

This is a skeleton: it does not perform ETL or row construction. Real
producer flows are expected to land canonical JSONL into a directory and
then invoke this script (or call :func:`build_package` / :func:`build_manifest`
directly) to package it.

Importable helpers used by tests and the smoke runner:

* :func:`_deterministic_id`
* :func:`_sha256_file`
* :func:`build_manifest`
* :func:`build_package`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Versions the FEDERATION "contract-sweeper-export" contract consumed by the
# spiderweb-pr query-hub (see the handshake constants below). This is the single
# source of truth for that version. It is INDEPENDENT of the finance-lane REPORT
# contract, which is versioned separately in readiness/contract_sweeper_finance_lane.py
# (currently 1.0.0) — the two share a constant name only, not a lineage.
EXPORT_CONTRACT_VERSION = "1.2.0"
PRODUCER_NAME = "contract-sweeper"
DEFAULT_PRODUCER_VERSION = "0.1.0"

# Cross-repo federation handshake. The query hub is a component inside the
# spiderweb-pr repo, not an independent repo. The hub keys ingestion off this
# descriptor; compatibility is matched against EXPORT_CONTRACT_VERSION above.
PRODUCER_REPO = "contract-sweeper"
CONSUMER_REPO = "spiderweb-pr"
CONSUMER_COMPONENT = "query-hub"
CONTRACT_NAME = "contract-sweeper-export"

STREAMS: tuple[tuple[str, str, str], ...] = (
    ("entities", "entities.jsonl", "contract_sweeper_entity.schema.json"),
    ("sources", "sources.jsonl", "contract_sweeper_source.schema.json"),
    ("funding_awards", "funding_awards.jsonl", "contract_sweeper_funding_award.schema.json"),
    ("transactions", "transactions.jsonl", "contract_sweeper_transaction.schema.json"),
    ("relationships", "relationships.jsonl", "contract_sweeper_relationship.schema.json"),
)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _deterministic_id(prefix: str, payload: dict[str, Any]) -> str:
    """Return ``<prefix>_<sha256(canonical_payload)[:32]>`` (lowercase)."""
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_jsonl_rows(path: Path) -> int:
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _resolve_source_path(input_dir: Path, canonical_name: str) -> Path:
    """Accept either canonical name or ``*.sample.*`` infix variant."""
    candidate = input_dir / canonical_name
    if candidate.exists():
        return candidate
    stem, suffix = canonical_name.rsplit(".", 1)
    sample_variant = input_dir / f"{stem}.sample.{suffix}"
    if sample_variant.exists():
        return sample_variant
    raise FileNotFoundError(
        f"missing stream file {canonical_name!r} (also looked for {stem}.sample.{suffix}) "
        f"in {input_dir}"
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_manifest(
    package_dir: Path,
    mode: str,
    producer_version: str = DEFAULT_PRODUCER_VERSION,
    created_at: str | None = None,
    extracted_at: str | None = None,
) -> dict[str, Any]:
    """Build a manifest dict by inspecting JSONL files already in ``package_dir``."""
    files: list[dict[str, Any]] = []
    for stream, filename, schema_id in STREAMS:
        path = package_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"missing stream file in package: {filename}")
        files.append(
            {
                "filename": filename,
                "stream": stream,
                "record_count": _count_jsonl_rows(path),
                "sha256": _sha256_file(path),
                "schema_id": schema_id,
            }
        )

    now = _utc_now_iso()
    package_payload = {
        "files": sorted([(f["filename"], f["sha256"]) for f in files]),
        "mode": mode,
    }
    package_id = _deterministic_id("pkg", package_payload)

    return {
        "package_id": package_id,
        "producer": PRODUCER_NAME,
        "producer_version": producer_version,
        "export_contract_version": EXPORT_CONTRACT_VERSION,
        "mode": mode,
        "created_at": created_at or now,
        "extracted_at": extracted_at or now,
        "federation": {
            "producer_repo": PRODUCER_REPO,
            "consumer_repo": CONSUMER_REPO,
            "consumer_component": CONSUMER_COMPONENT,
            "contract": CONTRACT_NAME,
        },
        "files": files,
    }


def build_package(
    input_dir: Path,
    output_dir: Path,
    mode: str = "test",
    producer_version: str = DEFAULT_PRODUCER_VERSION,
) -> Path:
    """Copy stream files into ``output_dir`` and write ``manifest.json``.

    Returns the manifest path.
    """
    if mode not in ("test", "production"):
        raise ValueError(f"invalid mode: {mode!r}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for _, canonical_name, _ in STREAMS:
        src = _resolve_source_path(input_dir, canonical_name)
        dst = output_dir / canonical_name
        shutil.copyfile(src, dst)

    manifest = build_manifest(
        output_dir,
        mode=mode,
        producer_version=producer_version,
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Contract-Sweeper federation export package.",
    )
    parser.add_argument(
        "--input-dir",
        default=str(REPO_ROOT / "exports" / "samples"),
        help="Directory containing pre-shaped JSONL stream files (default: exports/samples).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output package directory (default: exports/build_<utc-timestamp>/).",
    )
    parser.add_argument("--mode", choices=("test", "production"), default="test")
    parser.add_argument("--producer-version", default=DEFAULT_PRODUCER_VERSION)
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = REPO_ROOT / "exports" / f"build_{stamp}"
    else:
        output_dir = Path(args.output_dir).resolve()

    manifest_path = build_package(
        input_dir=input_dir,
        output_dir=output_dir,
        mode=args.mode,
        producer_version=args.producer_version,
    )
    print(f"[OK] wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
