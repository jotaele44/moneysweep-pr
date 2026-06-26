# NGO Political-Donation Materialization Runbook

Operator procedure for **populating** the political-donation coverage sources
added by the NGO build-out. Everything those sources declare is registered but
**empty** until this runbook is run — and it must run in a **network-enabled,
credentialed environment** (the Claude-Code web sandbox blocks outbound HTTPS,
so producers cannot fetch there).

See `docs/NGO_DONATION_COVERAGE.md` for what is linked and the residual gaps,
and `docs/NGO_INTEGRATION.md` for the NGO layer itself.

## Prerequisites

```bash
pip install -r requirements.txt
cp .env.example .env          # then edit; never commit real keys
```

| Credential | Needed for |
|---|---|
| `FEC_API_KEY` | FEC Schedule A + committees/Schedule B/E (free key at https://api.data.gov/signup/; `DEMO_KEY` works but is rate-capped at 30 req/hr) |

The PR feeds (CEE, OCE) and the IRS bulk drops are **manual** — no key, but an
operator must place export files in the dropzones below.

## Step 1 — Federal FEC (receipts + committees + outflows)

```bash
export FEC_API_KEY=<your key>

python3 scripts/download_fec.py              # Schedule A receipts (contributor_state=PR)
python3 scripts/download_fec_committees.py   # committee master + Schedule B + Schedule E
```

Outputs:

```text
data/staging/processed/pr_fec_contributions.csv
data/staging/processed/pr_fec_committees.csv
data/staging/processed/pr_fec_disbursements.csv
data/staging/processed/pr_fec_independent_expenditures.csv
```

Schedule B is the slow phase (per-committee × per-cycle). For a fast first pass:

```bash
python3 scripts/download_fec_committees.py --skip-disbursements --skip-expenditures
```

## Step 2 — PR donation feeds (manual dropzones)

```bash
# CEE / CEEPUR exports → data/raw/Donaciones/   then:
python3 scripts/ingest_donaciones.py

# OCE (Oficina del Contralor Electoral) exports → data/raw/OCE/   then:
python3 scripts/ingest_oce.py
```

Outputs `pr_donaciones.csv` and `pr_oce_donations.csv` (column-aligned so the
crossref consumes both uniformly).

## Step 3 — 990 political-activity signal

```bash
python3 scripts/download_nonprofits.py
```

Now emits `lobbying_expenditure`, `political_expenditure`, `schedule_c_filed`,
and the derived `politically_active` flag in `pr_nonprofits.csv`.

> Note: ProPublica does not reliably surface 990 Schedule C line items, so the
> flag is derived from subsection + whatever the API returns. Authoritative
> Schedule C extraction (IRS 990 e-file XML, AWS `s3://irs-form-990`) is a
> documented follow-up vector, not yet implemented.

## Step 4 — NGO layer + the donation crossref (the payoff)

Drop the NGO identity sources first, then build:

```text
data/raw/ngos/irs_eo_bmf/*.{csv,txt}
data/raw/ngos/teos/*.{csv,json,jsonl}
data/raw/ngos/pr_state_registry/*.csv
data/raw/ngos/usaspending/*.{csv,json,jsonl}
```

```bash
python3 scripts/ngo_integration.py
# builds ngos_master.csv, then AUTO-RUNS build_ngo_donation_crossref
```

Or run the crossref standalone against whatever feeds already exist:

```bash
python3 scripts/analyze_political_crossref.py --ngo
```

Output — the deliverable that answers "which NGOs are political donors":

```text
data/staging/processed/ngos/ngo_political_donations.csv
```

One row per matched NGO, with `donation_sources` (`federal_fec` / `pr` /
`both`), separate federal/PR aggregates, and `politically_active_subsection`
flagging 501(c)(4)/(5)/(6) as `likely_political`.

## Step 5 — Regenerate status and verify

```bash
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
python3 -c "from moneysweep.runtime import source_registry as sr; \
  r = sr.validate_registry(); print(r['ok'], r['errors'])"   # → True []
python -m pytest tests/ -q
```

## Definition of done

A source is `fully_materialized` (`scripts/gap_analysis_builder.py::_source_status`)
when **every** `expected_output` exists, is non-empty, and — for CSVs — has
`row_count ≥ validation_threshold.min_rows`. The derived crossref output
(`ngo_political_donations.csv`) is intentionally **not** a declared
`expected_output`, so it does not gate preflight; verify it by inspection and
the logged matched-NGO count.

## Future vectors (not in this runbook)

Tracked in `docs/NGO_DONATION_COVERAGE.md`:

1. Authoritative 990 Schedule C extraction from IRS e-file XML.
2. Committee → recipient entity resolution for `pr_fec_disbursements.csv` /
   `pr_fec_independent_expenditures.csv`.
3. Out-of-PR donors with PR linkage (reverse the `contributor_state=PR` filter).
4. Group-exemption rollups (attribute subordinate-org donations to the central org).
