"""Run the real GUI-test backend with an isolated credential store."""

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from scripts import manage_api_keys  # noqa: E402


def main() -> None:
    previous = manage_api_keys.ENV_PATH
    with TemporaryDirectory(prefix="moneysweep-gui-test-") as directory:
        manage_api_keys.ENV_PATH = Path(directory) / ".env"
        try:
            uvicorn.run(
                "server.backend.main:app",
                host="127.0.0.1",
                port=int(os.environ.get("GUI_BACKEND_PORT", "8000")),
            )
        finally:
            manage_api_keys.ENV_PATH = previous


if __name__ == "__main__":
    main()
