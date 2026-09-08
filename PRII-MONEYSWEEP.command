#!/bin/bash
# Double-click launcher (macOS). First run installs dependencies (needs
# internet once); later runs start the app directly and work offline.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/"
  read -r -p "Press Enter to close…"
  exit 1
fi

LOG="$(mktemp "${TMPDIR:-/tmp}/prii-moneysweep-pr-setup.XXXXXX")"
if ! "$PYTHON" desktop/setup.py --ensure >"$LOG" 2>&1; then
  cat "$LOG"
  echo
  echo "Setup failed. If Node.js is missing, install it from https://nodejs.org and re-run this launcher."
  echo "Full log: $LOG"
  [ -t 0 ] && read -r -p "Press Enter to close…"
  exit 1
fi
rm -f "$LOG"
exec .venv/bin/python desktop/launch.py "$@"
