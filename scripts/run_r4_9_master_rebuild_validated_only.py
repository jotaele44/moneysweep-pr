import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_sweeper.validation.master_rebuild_validated import run_r4_9_master_rebuild


if __name__ == "__main__":
    run_r4_9_master_rebuild(ROOT)
    print("wrote: data/exports/r4_9_rebuild_audit.csv")
    print("wrote: data/exports/rebuild_status.json")
