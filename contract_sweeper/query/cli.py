"""CLI implementation for the on-demand query function.

This module backs ``python -m contract_sweeper.query`` (see ``__main__``).
The flags mirror the :class:`Query` dataclass fields; outputs may be written
as parquet, CSV, or JSON. A JSON summary of per-source outcomes prints to
stdout unless ``--quiet`` is set.

Exit codes:
* ``0`` — every outcome is ``ok``, ``cache_hit``, or ``manual_only``.
* ``1`` — at least one outcome is ``error`` or output writing failed.
* ``2`` — argparse rejected the arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd

from contract_sweeper.runtime.source_registry import REPO_ROOT

from .adapters import ADAPTER_REGISTRY, ENTITY_ADAPTER_REGISTRY
from .dispatcher import query as run_query
from .types import Query, QueryResult, SourceQueryOutcome

_VALID_FORMATS = ("parquet", "csv", "json", "jsonl")


def _split_csv(values: Sequence[str] | None) -> list[str]:
    """Flatten ``--foo a,b --foo c`` into ``['a','b','c']`` (whitespace trimmed)."""
    if not values:
        return []
    out: list[str] = []
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _build_query(args: argparse.Namespace) -> Query:
    municipalities = tuple(_split_csv(args.municipality) + _split_csv(args.municipalities))
    fiscal_years = tuple(int(x) for x in _split_csv(args.fy) + _split_csv(args.fiscal_years))
    agencies = tuple(_split_csv(args.agency) + _split_csv(args.agencies))
    ueis = tuple(_split_csv(args.uei) + _split_csv(args.recipient_ueis))
    date_range = tuple(args.date_range) if args.date_range else None
    return Query(
        municipalities=municipalities,
        fiscal_years=fiscal_years,
        date_range=date_range,
        agencies=agencies,
        recipient_ueis=ueis,
    )


def _write_dataframe(df: pd.DataFrame, path: Path) -> None:
    suffix = path.suffix.lower().lstrip(".")
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == "parquet":
        df.to_parquet(path, index=False)
    elif suffix == "csv":
        df.to_csv(path, index=False)
    elif suffix == "jsonl":
        df.to_json(path, orient="records", lines=True)
    elif suffix == "json":
        df.to_json(path, orient="records")
    else:
        raise ValueError(
            f"unsupported output extension '.{suffix}' "
            f"(expected one of: {', '.join('.' + f for f in _VALID_FORMATS)})"
        )


def _outcome_dict(out: SourceQueryOutcome) -> dict:
    d = {"source_id": out.source_id, "status": out.status, "rows": out.rows}
    if out.fetched_at:
        d["fetched_at"] = out.fetched_at
    if out.error:
        d["error"] = out.error
    if out.reason:
        d["reason"] = out.reason
    return d


def _summary_payload(result: QueryResult) -> dict:
    payload = result.summary()
    payload["outcomes"] = [_outcome_dict(o) for o in result.outcomes.values()]
    return payload


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m contract_sweeper.query",
        description=(
            "Run an on-demand geographic + financial query across the "
            "registered Contract-Sweeper source adapters."
        ),
    )

    p.add_argument(
        "--municipality",
        action="append",
        metavar="NAME_OR_FIPS",
        help="Municipality name or FIPS code (repeatable).",
    )
    p.add_argument(
        "--municipalities",
        action="append",
        metavar="CSV",
        help="Comma-separated municipalities.",
    )
    p.add_argument("--fy", action="append", metavar="YEAR", help="Fiscal year (repeatable).")
    p.add_argument(
        "--fiscal-years", action="append", metavar="CSV", help="Comma-separated fiscal years."
    )
    p.add_argument(
        "--date-range",
        nargs=2,
        metavar=("START", "END"),
        help="ISO date range, e.g. --date-range 2023-01-01 2023-12-31.",
    )
    p.add_argument(
        "--agency", action="append", metavar="NAME", help="Awarding agency (repeatable)."
    )
    p.add_argument("--agencies", action="append", metavar="CSV", help="Comma-separated agencies.")
    p.add_argument("--uei", action="append", metavar="UEI", help="Recipient UEI (repeatable).")
    p.add_argument("--recipient-ueis", action="append", metavar="CSV", help="Comma-separated UEIs.")

    p.add_argument(
        "--source",
        action="append",
        metavar="SID",
        help="Source-registry source_id to query (repeatable). Defaults to every registered adapter.",
    )
    p.add_argument("--sources", action="append", metavar="CSV", help="Comma-separated source_ids.")

    p.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "Combined output file. Format inferred from extension: "
            ".parquet / .csv / .json / .jsonl."
        ),
    )
    p.add_argument(
        "--output-dir",
        metavar="DIR",
        help="Write per-source files <DIR>/<source_id>.<format>.",
    )
    p.add_argument(
        "--format",
        choices=_VALID_FORMATS,
        default="parquet",
        help="File format when --output-dir is used (default: parquet).",
    )

    p.add_argument("--force-refresh", action="store_true", help="Bypass the cache.")
    p.add_argument(
        "--list-adapters",
        action="store_true",
        help="Print the registered geographic adapter source_ids and exit.",
    )
    p.add_argument(
        "--list-entity-adapters",
        action="store_true",
        help="Print the registered entity-mode adapter source_ids and exit.",
    )
    p.add_argument(
        "--root",
        metavar="PATH",
        help="Repo root override (defaults to the installed package's REPO_ROOT).",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress the JSON summary on stdout.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_adapters:
        for sid in sorted(ADAPTER_REGISTRY.keys()):
            print(sid)
        return 0

    if args.list_entity_adapters:
        for sid in sorted(ENTITY_ADAPTER_REGISTRY.keys()):
            print(sid)
        return 0

    criteria = _build_query(args)
    source_ids = _split_csv(args.source) + _split_csv(args.sources)
    root = Path(args.root) if args.root else REPO_ROOT

    result = run_query(
        criteria,
        source_ids=source_ids or None,
        root=root,
        force_refresh=args.force_refresh,
    )

    try:
        if args.output:
            _write_dataframe(result.combined, Path(args.output))
        if args.output_dir:
            out_dir = Path(args.output_dir)
            for sid, outcome in result.outcomes.items():
                if outcome.status not in ("ok", "cache_hit") or outcome.df is None:
                    continue
                if len(outcome.df) == 0:
                    continue
                _write_dataframe(outcome.df, out_dir / f"{sid}.{args.format}")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(json.dumps(_summary_payload(result), indent=2, default=str))

    error_count = sum(1 for o in result.outcomes.values() if o.status == "error")
    return 1 if error_count else 0
