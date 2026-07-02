# moneysweep-pr — MoneySweep Producer (PRII federation)

![Tests](https://github.com/jotaele44/moneysweep-pr/actions/workflows/tests.yml/badge.svg)

`moneysweep-pr` is the public-money intelligence producer for the Puerto Rico Integrated Intelligence (PRII) federation. Its federation alias is `moneysweep-pr`.

The pipeline acquires, normalizes, validates, and cross-links public procurement, infrastructure, lobbying, campaign-finance, debt/fiscal-control, contractor-reference, recovery-assistance, and geospatial records. It exports reviewable records for [`thehub-pr`](https://github.com/jotaele44/thehub-pr), where cross-producer aggregation and correlation occur.

## Weekly watch registry

This repository now includes a network-free weekly watch layer for government, municipal, oversight, media, and official-account monitoring.

```text
registry/watch_sources.json
docs/WEEKLY_WATCH_PIPELINE.md
scripts/build_weekly_watch_update.py
reports/weekly_watch_update_plan.json
```

Run:

```bash
python3 scripts/build_weekly_watch_update.py --strict
```

Official-account and media entries are `informative_only`: they may create leads, aliases, and corroboration tasks, but they cannot promote records without a stronger source.

## Federation role

| Field | Value |
|---|---|
| Repository | `jotaele44/moneysweep-pr` |
| Federation alias | `moneysweep-pr` |
| Parent hub | [`thehub-pr`](https://github.com/jotaele44/thehub-pr) |
| Primary function | Public money, procurement, grants, recovery, influence, fiscal-control, contractor-reference, and disaster-assistance producer |
| Production stance | Not production-certified master dataset until gates pass |

## Quick start

```bash
git clone https://github.com/jotaele44/moneysweep-pr.git
cd moneysweep-pr
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
python3 run_all.py --only-setup --strict-preflight
python3 scripts/build_weekly_watch_update.py --strict
```
