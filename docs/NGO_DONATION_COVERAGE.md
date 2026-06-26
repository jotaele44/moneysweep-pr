# NGO / Non-Profit Political-Donation Coverage

This doc tracks how moneysweep-pr covers the question:

> *Which Puerto Rico NGOs and other not-for-profits are likely sources of
> political donations, and where are the remaining blind spots?*

## What is linked

The political-donation coverage stack now spans four layers:

| Layer | Source(s) | Output | Family |
|---|---|---|---|
| **Federal donor receipts** | FEC Schedule A (`download_fec.py`) | `pr_fec_contributions.csv` | political_finance |
| **Federal committee + outflows** | FEC committee master + Schedule B + Schedule E (`download_fec_committees.py`) | `pr_fec_committees.csv`, `pr_fec_disbursements.csv`, `pr_fec_independent_expenditures.csv` | political_finance |
| **PR donor / committee filings** | CEE (`ingest_donaciones.py`), OCE (`ingest_oce.py`) | `pr_donaciones.csv`, `pr_oce_donations.csv` | political_finance |
| **NGO identity universe** | IRS EO BMF / TEOS / PR state registry (`ngo_integration.py`) | `ngos_master.csv` (with IRS subsection / NTEE) | nonprofit |

The bridge between the donation feeds and the NGO universe is
`analyze_political_crossref.build_ngo_donation_crossref`, which produces
`data/staging/processed/ngos/ngo_political_donations.csv` — one row per NGO
that appears as a donor on federal FEC and/or PR (CEE/OCE) filings. The
crossref also flags each NGO's IRS subsection:

- 501(c)(4)/(5)/(6) → `likely_political` (social welfare / labor / business
  leagues — the subsections most likely to engage in politics).
- 501(c)(3) → `restricted_charity` (restricted from political-campaign
  intervention).
- everything else → `other`.

The 990 layer adds a second, independent signal: `politically_active` in
`pr_nonprofits.csv` is true when subsection ∈ {4,5,6} *or* ProPublica reports
non-zero lobbying / political expenditure.

## Remaining gaps (residual blind spots)

These are real gaps in coverage. They are **not** implemented and should be
treated as future vectors.

1. **Authoritative 990 Schedule C extraction.** ProPublica does not reliably
   surface 990 Schedule C line items. A nonprofit's actual political /
   lobbying spending is in the IRS 990 e-file XML on the AWS public dataset
   (s3://irs-form-990). A follow-up vector should parse Schedule C from those
   XML filings and feed `political_expenditure` / `lobbying_expenditure` with
   authoritative numbers instead of opportunistic API field probing.

2. **Committee → recipient resolution.** `pr_fec_disbursements.csv` and
   `pr_fec_independent_expenditures.csv` give us PAC / Super PAC / 527 outflows,
   but recipients are free-text names. They are not entity-resolved against the
   awards master, NGO master, or `entities_resolved.csv`. A follow-up vector
   should run them through the same entity-resolution pipeline used for awards.

3. **Out-of-PR donors with PR linkage.** `download_fec.py` filters Schedule A
   by `contributor_state=PR`. PR-linked organizations that file with a mainland
   address are missed. A follow-up vector should reverse the join (filter FEC
   contributions by `contributor_employer` / `committee_id` linked to PR
   committees, rather than only by donor state).

4. **OCE / CEE feed depth.** Both `ingest_donaciones.py` (CEE) and
   `ingest_oce.py` (OCE) are dropzone readers — they consume operator-delivered
   exports. Neither has a live scraper or API integration. Coverage depth is
   bounded by what an operator manually places in
   `data/raw/Donaciones/` and `data/raw/OCE/`.

5. **Group-exemption rollups.** NGO group exemptions (parent → subordinate
   relationships) are tracked in `ngo_fiscal_sponsor_edges.csv` but are not
   currently rolled up into the donation crossref. A follow-up vector should
   attribute subordinate-org donations to the central org for analytical
   purposes.

## Verification

```bash
python -m pytest \
  tests/test_ngo_donation_crossref.py \
  tests/test_ingest_oce.py \
  tests/test_download_nonprofits_political_fields.py \
  tests/test_source_registry.py -v

python3 -c "from moneysweep.runtime import source_registry as sr; \
  r = sr.validate_registry(); print(r['ok'], r['errors'])"
# → True []

python3 scripts/analyze_political_crossref.py --ngo
ls -l data/staging/processed/ngos/ngo_political_donations.csv

python3 scripts/ngo_integration.py
```
