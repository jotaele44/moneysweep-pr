# LDA.gov API Adapter

## Status

`lda_gov` is an API-authoritative federal lobbying source. It replaces uploaded/static LDA registrant, client, filing, lobbyist, contribution, and constants snapshots with reproducible normalized outputs.

## Base URL

```text
https://lda.gov/api/v1/
```

## Endpoint map

- `filings`: `/api/v1/filings/`
- `contributions`: `/api/v1/contributions/`
- `registrants`: `/api/v1/registrants/`
- `clients`: `/api/v1/clients/`
- `lobbyists`: `/api/v1/lobbyists/`
- `constants/filing/filingtypes`: `/api/v1/constants/filing/filingtypes/`
- `constants/filing/lobbyingactivityissues`: `/api/v1/constants/filing/lobbyingactivityissues/`
- `constants/filing/governmententities`: `/api/v1/constants/filing/governmententities/`
- `constants/general/countries`: `/api/v1/constants/general/countries/`
- `constants/general/states`: `/api/v1/constants/general/states/`
- `constants/lobbyist/prefixes`: `/api/v1/constants/lobbyist/prefixes/`
- `constants/lobbyist/suffixes`: `/api/v1/constants/lobbyist/suffixes/`
- `constants/contribution/itemtypes`: `/api/v1/constants/contribution/itemtypes/`

## Execution mode

Default mode is dry-run fixture mode. It performs no network calls and writes deterministic synthetic outputs.

```bash
python scripts/sources/fetch_lda_gov.py --output-dir . --limit 1
```

Live mode requires explicit opt-in:

```bash
python scripts/sources/fetch_lda_gov.py --live --output-dir . --limit 100
```

No API key is required.

## Raw payload policy

Raw API payloads are not persisted by default. Normalized rows set:

```text
raw_payload_stored = false
```

The `--include-raw` flag exists for controlled debugging only and should not be used for committed production outputs unless repo data policy explicitly allows it.

## Output paths

Normalized tables:

```text
outputs/normalized/lda/lda_registrants.csv
outputs/normalized/lda/lda_clients.csv
outputs/normalized/lda/lda_lobbyists.csv
outputs/normalized/lda/lda_filings.csv
outputs/normalized/lda/lda_contributions.csv
```

Reference tables:

```text
outputs/reference/lda/lda_ref_filing_types.csv
outputs/reference/lda/lda_ref_lobbying_issues.csv
outputs/reference/lda/lda_ref_government_entities.csv
outputs/reference/lda/lda_ref_countries.csv
outputs/reference/lda/lda_ref_states.csv
outputs/reference/lda/lda_ref_lobbyist_prefixes.csv
outputs/reference/lda/lda_ref_lobbyist_suffixes.csv
outputs/reference/lda/lda_ref_contribution_item_types.csv
```

Compatibility mirror:

```text
data/staging/processed/pr_lda_filings.csv
```

Reports:

```text
reports/lda_api_readiness.json
reports/lda_static_seed_replacement_report.json
reports/lda_api_checkpoint.json
```

## Evidence-tier treatment

Direct LDA API records are treated as `T1` source records. Cross-source entity links derived from normalized LDA records should be treated as `T2`; fuzzy entity matches remain review-required until manually confirmed.

## Static seed replacement policy

Uploaded/static LDA snapshots are no longer source-of-truth after this adapter is enabled. They may be retained as:

- `regression_fixture`
- `archival_snapshot`
- parser-test fixture

They should not overwrite fresh API-normalized outputs.
