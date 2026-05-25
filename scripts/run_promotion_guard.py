"""Run the master-promotion guard (issue #86).

Exit code 0 when the build is eligible for promotion to master (including
the common case where no production tier is claimed). Exit code 1 when a
validated tier is claimed without supporting evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.promotion_guard import run_guard


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard master promotion against non-validated builds")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON")
    args = parser.parse_args()

    result = run_guard(Path(args.root))

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"claimed_status: {result['claimed_status']}")
        print(f"promotion_claimed: {result['promotion_claimed']}")
        print(f"eligible: {result['eligible']}")
        print(result["message"])
        for condition in result["unmet_conditions"]:
            print(f"  - unmet: {condition}")

    return 0 if result["eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
