import sys

import scripts.scrape_iapconsulta as iap


def test_iapconsulta_cli_returns_nonzero_when_partial_rows_have_errors(monkeypatch):
    monkeypatch.setattr(
        iap,
        "_run",
        lambda **_kwargs: {
            "rows": 4120,
            "path": "data/staging/processed/pr_contralor_audits.csv",
            "errors": ["scrape stopped early"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["scrape_iapconsulta.py"])

    assert iap.main() == 1


def test_iapconsulta_cli_returns_zero_only_for_error_free_acquisition(monkeypatch):
    monkeypatch.setattr(
        iap,
        "_run",
        lambda **_kwargs: {
            "rows": 4129,
            "path": "data/staging/processed/pr_contralor_audits.csv",
            "errors": [],
        },
    )
    monkeypatch.setattr(sys, "argv", ["scrape_iapconsulta.py"])

    assert iap.main() == 0
