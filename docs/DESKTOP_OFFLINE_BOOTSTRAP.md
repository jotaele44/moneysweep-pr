# Offline first run for the desktop wrapper

The source-checkout desktop wrapper needs two things on a machine that has never
run it: a built dashboard, and the Python packages in
`requirements.txt`, `server/backend/requirements.txt` and
`requirements-desktop.txt`.

The dashboard is already solved — a prebuilt bundle is committed at
`desktop/prebuilt-dashboard/`, so **Node.js is never required** and that half of
the first run is offline by construction.

This document covers the other half: installing the Python packages with no
network, which is the usual case when moving the app to a second machine.

## Why the packages are not vendored into the repository

Deliberate, not an oversight:

- The runtime set is heavy binary wheels — `pyarrow` (~35 MB), `duckdb` (~20 MB),
  `numpy` (~20 MB), `pandas` (~12 MB) — and each one individually exceeds the
  5 MiB per-file ceiling enforced by `.github/workflows/size-guard.yml`. Committing
  them would require a dozen allowlist entries and gut the guard that
  `docs/HISTORY_PURGE_PLAN.md` (#222) exists to maintain.
- Wheels are specific to platform, CPU architecture *and* CPython minor version.
  Covering macOS arm64 + macOS x86_64 + Linux + Windows across the supported
  interpreters is roughly 1.5 GB, and it goes stale on every constraint bump.
- Two requirements resolve from `git+https://` URLs (`prii-maintenance` and
  `prii-desktop`), so they cannot be served from an ordinary package index at all.

A wheel cache the operator creates once is cheaper and always current.

## Procedure

**On a machine where the app already works** (same OS, same CPU architecture and
same Python minor version as the target — a wheel built for macOS arm64/CPython
3.11 will not install on Intel or on 3.13):

```bash
cd moneysweep-pr
python3 -m pip download \
  -r requirements.txt \
  -r server/backend/requirements.txt \
  -r requirements-desktop.txt \
  -c constraints-desktop.txt \
  -d desktop/wheelhouse
```

`pip download` builds wheels for the two `git+https://` requirements as well, so
the cache is complete and the target machine needs neither PyPI nor GitHub.

**Copy `desktop/wheelhouse/` into the checkout on the target machine**, then start
the app normally. Setup detects the directory and installs with
`--no-index --find-links desktop/wheelhouse`, so nothing touches the network. It
prints the wheelhouse path it is using, and `desktop/preflight.py` reports
`Using the offline wheelhouse; no downloads needed.` instead of probing hosts.

`desktop/wheelhouse/` is gitignored — it is an operator artifact, never committed.

## Using a wheelhouse from elsewhere

```bash
PRII_WHEELHOUSE=/Volumes/transfer/moneysweep-wheels python3 desktop/setup.py
```

## Checking what is blocking a first run

```bash
python3 desktop/preflight.py          # human-readable
python3 desktop/preflight.py --json   # machine-readable
```

It reports each prerequisite separately — checkout integrity, writability, Python
version, `venv`, dashboard availability, `git`, PyPI/GitHub reachability, and free
disk — and names the remedy for whichever one failed. Network hosts are probed
only when package installation is actually still outstanding.
