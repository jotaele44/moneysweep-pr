# Capital and Control Sources v0.2

## Scope

This stacked vector extends the certified v0.1 runtime core with an authoritative-source registry, filing-denominator classifier, SEC fair-access acquisition/freezing controls, complete-filing 13F materialization gates, and the first source-specific parser: SEC Form 13F information-table XML.

It does **not** claim universal capital-market source exhaustion. The initial authoritative SEC source universe is bounded to four filing families that materially support capital/control analysis: Form 13F, Schedule 13D/13G, Forms 3/4/5, and Form N-PORT.

## Authoritative source registry

All registered sources are U.S. Securities and Exchange Commission sources. Search engines are discovery only and cannot establish a filing denominator.

| Source key | Filing family | Canonical semantic role | Denominator rule |
|---|---|---|---|
| `SEC_13F` | 13F-HR / amendments / notices | institutional investment discretion | enumerate EDGAR or SEC quarterly 13F data universe; preserve amendments |
| `SEC_13D_G` | Schedule 13D / 13G + amendments | beneficial-ownership disclosure | enumerate exact EDGAR schedule types; preserve reported-person/group distinctions |
| `SEC_FORMS_3_4_5` | Forms 3, 4, 5 + amendments | Section 16 ownership/transactions | enumerate exact EDGAR ownership submissions by issuer/reporting-owner scope |
| `SEC_NPORT` | N-PORT family | registered-fund portfolio holdings | enumerate exact EDGAR N-PORT submissions; do not collapse fund/adviser/parent identity |

Official reference points:

- SEC Form 13F data sets: `https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets`
- SEC EDGAR technical specifications: `https://www.sec.gov/submit-filings/technical-specifications`
- SEC EDGAR filing search: `https://www.sec.gov/edgar/search/`

As observed on 2026-08-15, the SEC 13F bulk-data page identifies a published dataset history from July 2013 through May 2026 and describes quarterly updates. The SEC technical-specification index lists structured specifications for Form 13F, Schedule 13D/13G, Ownership Forms 3/4/5, and N-PORT. These web observations define discovery and implementation references; a reproducible denominator still requires freezing the actual enumerated source bytes/index rows.

## SEC fair-access acquisition and freezing contract

`SECFairAccessClient` provides the bounded network acquisition layer used before a source can be treated as a frozen manifestation. Acquisition is source transport, not evidence interpretation.

Safeguards:

- HTTPS is mandatory;
- the request and final successful response URL must resolve to the explicit SEC host allowlist;
- the caller must provide a non-empty application identifier and contact in the `User-Agent`;
- CR/LF header injection is rejected;
- the configured request rate must be positive and cannot exceed 10 requests per second; the default is 5 requests per second;
- monotonic rate limiting is applied between requests;
- retryable HTTP states are bounded to 403, 429, 500, 502, 503, and 504;
- transport timeouts and request/network errors use bounded retry/backoff;
- `Retry-After` supports both numeric seconds and HTTP-date syntax, including case-insensitive header names;
- non-retryable HTTP failures fail immediately;
- empty bodies fail closed;
- unexpected content types fail closed;
- optional expected byte-size and SHA-256 gates fail closed before persistence;
- provenance receipts preserve request URL, final response URL, HTTP status, UTC retrieval time, attempt count, content type, `Content-Length`, `ETag`, `Last-Modified`, byte size, and SHA-256;
- retrieval clocks must be explicitly UTC, not merely timezone-aware;
- persistence uses a same-directory temporary file, flush + `fsync`, then atomic `os.replace`;
- an existing destination with identical bytes is idempotently classified `EXISTING_MATCH`;
- an existing destination with different bytes is never overwritten silently;
- persisted bytes are re-read and verified against receipt byte size and SHA-256; a post-write mismatch removes the bad output and fails closed.

The acquisition client does not certify that an index, filing, or source family is complete. It only certifies the byte manifestation actually fetched and frozen under the request identity recorded in the receipt.

## Denominator contract

`build_filing_denominator()` only classifies a supplied authoritative filing-index universe. It never performs text search and never treats search results as exhaustive.

Required invariants:

- accession number uniqueness;
- SEC-hosted source locator;
- filing date cannot precede period of report;
- exact form-type inclusion;
- retained + excluded = input count;
- every exclusion is classified;
- amendments remain separate filing records.

## SEC 13F adapter

`FrozenSEC13FAdapter` consumes frozen `informationTable` XML bytes and explicit filing metadata.

Safeguards:

- exact XML root required;
- explicit SEC accession and filer CIK;
- explicit filing date and period of report;
- explicit `value_scale` to prevent historical unit mistakes;
- byte size and SHA-256 are computed from the supplied bytes;
- row count is derived from XML and closes through canonical ingestion;
- each `infoTable` remains one whole source row;
- no issuer-name normalization is used as identity proof;
- the reporting manager is represented as `INV_SEC_CIK_<CIK>`;
- the reported CUSIP is preserved as a security identifier, not promoted to legal-issuer identity;
- position class is `INVESTMENT_DISCRETION`;
- beneficial-owner, adviser, and control states remain `UNKNOWN` unless another source binds them;
- `otherManager`, put/call, FIGI, raw value, raw class, and raw voting fields remain in `extra`;
- amendments require explicit row-to-prior-observation supersession binding before canonical `AMENDED` status is emitted.

## Complete-filing materialization gate

`materialize_sec_13f()` and `scripts/materialize_sec_13f.py` require the SEC primary XML and information-table XML from the same EDGAR filing directory. A `CANONICAL` run additionally requires authoritative expected byte sizes for both files before the fetch starts.

The materializer:

- freezes both files independently and preserves separate SHA-256/size receipts;
- parses `tableEntryTotal` and `tableValueTotal` from the primary filing XML;
- parses every top-level `infoTable` row without aggregation;
- requires parsed row count to equal the primary-declared table-entry total;
- requires the sum of parsed `market_value` observations to equal the primary-declared table-value total exactly through decimal reconciliation;
- preserves the raw files even if a downstream reconciliation fails, so a failed interpretation cannot erase acquired evidence;
- emits `PASS` only for a `CANONICAL` target whose byte-size and row/value gates all close; otherwise the materialization remains `PROVISIONAL` or fails closed.

The first real-world target is SEC accession `0001193125-26-226661`, filer CIK `0001067983`, filed 2026-05-15 for period 2026-03-31. The SEC filing index identifies exactly two public documents in the filing directory: `primary_doc.xml` at 5,555 bytes and the information table `53405.xml` at 45,259 bytes. The exact acquisition URLs are:

- `https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/primary_doc.xml`
- `https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/53405.xml`

Reference execution:

```bash
python scripts/materialize_sec_13f.py \
  --accession 0001193125-26-226661 \
  --filer-cik 0001067983 \
  --filing-date 2026-05-15 \
  --period-of-report 2026-03-31 \
  --primary-url https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/primary_doc.xml \
  --information-table-url https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/53405.xml \
  --expected-primary-size 5555 \
  --expected-information-table-size 45259 \
  --output-dir evidence/capital_control/sec/0001193125-26-226661 \
  --contact YOUR_CONTACT
```

The command writes the raw XML manifestations plus `materialization.json`, which contains both retrieval identities, hashes, byte sizes, declared totals, parsed totals, and the canonical source manifest.

## First real-world materialization fixture

The regression fixture `sec_13f_0001193125_26_226661_excerpt.xml` is a **derived two-row excerpt**, not a byte-identical copy of the complete SEC filing. It reproduces the first two `infoTable` observations from SEC accession `0001193125-26-226661`, filed 2026-05-15 for period 2026-03-31 by filer CIK `0001067983`.

Because the fixture is an excerpt reconstructed from the authoritative filing, its manifest is deliberately `NONCANONICAL`. It proves parser behavior against real reported values but cannot certify the complete filing byte manifestation or the full filing denominator.

The complete filing still must be executed through the materializer on a network-enabled host before the filing itself is promoted to `PASS`.

## Certification boundary

This vector is `PASS_BOUNDED` for source-registry contracts, SEC fair-access acquisition/freezing behavior, denominator classification behavior, 13F parsing semantics, and the complete-filing materialization/reconciliation implementation after CI passes. It does not by implementation alone certify:

- successful acquisition of the complete bytes of accession `0001193125-26-226661`;
- the resulting SHA-256 values until a network-enabled materialization run is frozen;
- complete SEC filing denominators for any issuer, manager, or date range beyond an explicitly enumerated universe;
- beneficial ownership from 13F alone;
- issuer legal identity from CUSIP alone;
- current investor rankings;
- Schedule 13D/G, Forms 3/4/5, or N-PORT row parsers;
- API or GUI workflows.
