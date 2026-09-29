from scripts import download_fdic


def test_fdic_output_schema_carries_origin_and_scope():
    assert "origin" in download_fdic.INST_OUTPUT_COLUMNS
    assert "financial_scope" in download_fdic.INST_OUTPUT_COLUMNS
    assert "origin" in download_fdic.FIN_OUTPUT_COLUMNS
    assert "financial_scope" in download_fdic.FIN_OUTPUT_COLUMNS


def test_fdic_seed_constants_do_not_claim_authoritative_origin():
    # Seeds are intentionally unlabeled constants; run() must attach
    # FALLBACK_SEED only when materializing them.
    assert all("origin" not in row for row in download_fdic.KNOWN_FDIC_INSTITUTIONS)
    assert all("origin" not in row for row in download_fdic.KNOWN_FDIC_FINANCIALS)
