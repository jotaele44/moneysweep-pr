"""
Setup the directory structure for the Puerto Rico Federal Contracts Data Pipeline.
Creates all required directories and .gitkeep files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import ALL_DIRS, PROJECT_ROOT, setup_logging


def main(root: Path | None = None) -> int:
    """Create all pipeline directories. Returns 0 on success."""
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("setup")
    logger.info("Setting up directory structure...")

    leaf_dirs = [
        root / "data" / "staging" / "expansion",
        root / "data" / "staging" / "processed",
        root / "data" / "raw",
        root / "data" / "logs",
    ]

    for d in ALL_DIRS:
        existed = d.exists()
        d.mkdir(parents=True, exist_ok=True)
        logger.info(f"  Directory: {d.relative_to(root)} {'(ok)' if existed else '(created)'}")

    # Add .gitkeep to leaf directories
    for d in leaf_dirs:
        d.mkdir(parents=True, exist_ok=True)
        gitkeep = d / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
            logger.info(f"  Created: {gitkeep.relative_to(root)}")

    logger.info("Directory setup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
