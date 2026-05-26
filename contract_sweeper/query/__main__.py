"""Entry point shim for ``python -m contract_sweeper.query``.

The actual implementation lives in :mod:`contract_sweeper.query.cli` so the
package's ``__init__`` can re-export ``main`` without colliding with the
``runpy`` machinery that re-executes ``__main__`` modules.
"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
