"""Import registry-declared source outputs into the MoneySweep source database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moneysweep.runtime.source_database import materialize_sources
from moneysweep.runtime.source_registry import all_sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--include-manual", action="store_true")
    args = parser.parse_args()
    sources = all_sources(args.root)
    if args.source:
        wanted = set(args.source)
        sources = [source for source in sources if source["source_id"] in wanted]
    elif not args.include_manual:
        sources = [
            source for source in sources if source.get("required") or source.get("producer_script")
        ]
    print(json.dumps(materialize_sources(args.root, sources), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
