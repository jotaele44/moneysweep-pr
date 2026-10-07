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


class _Session:
    def close(self):
        pass


def test_materialized_fallback_rows_are_explicitly_labeled(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(download_fdic, "_session", lambda: _Session())
    monkeypatch.setattr(
        download_fdic,
        "_download_institutions",
        lambda session, logger: pd.DataFrame(columns=download_fdic.INST_OUTPUT_COLUMNS),
    )
    monkeypatch.setattr(
        download_fdic,
        "_download_financials",
        lambda session, certs, logger: pd.DataFrame(columns=download_fdic.FIN_OUTPUT_COLUMNS),
    )

    result = download_fdic.run(root=tmp_path, force=True)
    inst = pd.read_csv(result["inst_path"], dtype=str)
    fin = pd.read_csv(result["fin_path"], dtype=str)
    assert set(inst["origin"]) == {"FALLBACK_SEED"}
    assert set(fin["origin"]) == {"FALLBACK_SEED"}
    assert set(inst["financial_scope"]) == {"INSTITUTION_WIDE"}
    assert set(fin["financial_scope"]) == {"INSTITUTION_WIDE"}
