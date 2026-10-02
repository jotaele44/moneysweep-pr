"""Desktop composition root for MoneySweep.

The normal backend remains a thin read-only layer over repository canonical
files. The standalone desktop build composes that backend with the writable
Application-Support workspace and the local materialization control plane.
"""

from __future__ import annotations

import os
from pathlib import Path

from server.backend import main as core
from server.backend.materialization import router as materialization_router

# desktop.launch bootstraps this before importing the ASGI app. Fail closed if a
# frozen desktop process somehow reaches this module without a writable data root.
_data_root = os.environ.get("MONEYSWEEP_DATA_ROOT")
if not _data_root:
    raise RuntimeError("MONEYSWEEP_DATA_ROOT is unset; desktop workspace was not bootstrapped")

core.CANON = Path(_data_root) / "canonical_v1"
core._load()

app = core.app
app.include_router(materialization_router)
