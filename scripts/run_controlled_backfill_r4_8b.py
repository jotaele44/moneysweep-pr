import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_sweeper.validation.controlled_backfill import run_controlled_backfill


if __name__ == "__main__":
    run_controlled_backfill(ROOT)
    print("wrote: data/exports/controlled_backfill_execution_results_r4_8b.csv")
    print("wrote: data/review_queue/source_backfill_failures_r4_8b.csv")
    print("wrote: data/review_queue/source_backfill_no_data_r4_8b.csv")
    print("wrote: data/review_queue/source_backfill_manual_fallback_r4_8b.csv")
    print("wrote: data/review_queue/source_backfill_credential_failures_r4_8b.csv")
    print("wrote: data/exports/rebuild_status.json")
