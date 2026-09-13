#!/bin/sh
# Launcher (Linux). Double-click where your file manager allows executing
# scripts, or run ./PRII-MONEYSWEEP.sh. First run installs dependencies (needs
# internet once); later runs start the app directly and work offline.
set -eu
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required (e.g. sudo apt install python3 python3-venv)."
  exit 1
fi

LOG="$(mktemp "${TMPDIR:-/tmp}/prii-moneysweep-pr-setup.XXXXXX")"
if ! python3 desktop/setup.py --ensure >"$LOG" 2>&1; then
  cat "$LOG"
  echo
  echo "Setup failed. If Node.js is missing, install it from https://nodejs.org and re-run this launcher."
  echo "Full log: $LOG"
  if [ -t 0 ]; then
    printf '%s' "Press Enter to close… "
    read -r _
  fi
  exit 1
fi
rm -f "$LOG"
exec .venv/bin/python desktop/launch.py "$@"
