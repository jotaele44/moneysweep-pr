#!/usr/bin/env python3
"""Generate PREPA stakeholder overlap reports.

Pipeline:
1. Load structured PREPA service-matrix CSV.
2. Build normalized stakeholder nodes.
3. Load contract/procurement datasets.
4. Run overlap correlation.
5. Emit confidence-ranked JSON report.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from moneysweep.modules.prepa_titleiii_entity_graph import (
    build_nodes,
    export_graph,
    match_contract_records,
)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PREPA overlap intelligence report")
    parser.add_argument("service_matrix_csv", type=Path)
    parser.add_argument("datasets", nargs="+", help="CSV datasets to correlate against")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    rows = load_csv(args.service_matrix_csv)
    nodes = build_nodes(rows, source_document="PREPA Title III service matrix")

    flags = []
    for dataset in args.datasets:
        dataset_path = Path(dataset)
        records = load_csv(dataset_path)
        flags.extend(
            match_contract_records(
                nodes,
                records,
                dataset_name=dataset_path.name,
            )
        )

    flags = sorted(flags, key=lambda x: x.confidence, reverse=True)
    export_graph(nodes, flags, args.output)

    summary = {
        "nodes": len(nodes),
        "flags": len(flags),
        "top_confidence": flags[0].confidence if flags else 0,
        "datasets": [Path(d).name for d in args.datasets],
        "output": str(args.output),
    }

    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
