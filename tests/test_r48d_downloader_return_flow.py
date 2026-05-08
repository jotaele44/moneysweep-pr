"""Return-flow tests for R4.8D downloader allow-empty semantics."""

from __future__ import annotations

import scripts.download_sba as download_sba
import scripts.download_sbir as download_sbir
import scripts.download_subawards as download_subawards
import scripts.download_usace_civil as download_usace_civil


def test_download_sba_main_return_flow(monkeypatch):
    monkeypatch.setattr(
        download_sba,
        "_run",
        lambda force=False: {
            "raw_rows": 10,
            "rows": 5,
            "master_path": "x.csv",
            "status": "OK",
        },
    )
    monkeypatch.setattr(download_sba.sys, "argv", ["download_sba.py"])
    assert download_sba.main() == 0

    monkeypatch.setattr(
        download_sba,
        "_run",
        lambda force=False: {
            "raw_rows": 0,
            "rows": 0,
            "master_path": "x.csv",
            "status": "EMPTY",
        },
    )
    monkeypatch.setattr(download_sba.sys, "argv", ["download_sba.py"])
    assert download_sba.main() == 1

    monkeypatch.setattr(download_sba.sys, "argv", ["download_sba.py", "--allow-empty-success"])
    assert download_sba.main() == 0


def test_download_sbir_main_return_flow(monkeypatch):
    monkeypatch.setattr(
        download_sbir,
        "_run",
        lambda force=False: {
            "raw_rows": 3,
            "rows": 2,
            "status": "OK",
        },
    )
    monkeypatch.setattr(download_sbir.sys, "argv", ["download_sbir.py"])
    assert download_sbir.main() == 0

    monkeypatch.setattr(
        download_sbir,
        "_run",
        lambda force=False: {
            "raw_rows": 0,
            "rows": 0,
            "status": "EMPTY",
        },
    )
    monkeypatch.setattr(download_sbir.sys, "argv", ["download_sbir.py"])
    assert download_sbir.main() == 1

    monkeypatch.setattr(download_sbir.sys, "argv", ["download_sbir.py", "--allow-empty-success"])
    assert download_sbir.main() == 0


def test_download_subawards_main_return_flow(monkeypatch):
    monkeypatch.setattr(
        download_subawards,
        "_run",
        lambda force=False, fy_start=None: {
            "raw_rows": 100,
            "master_rows": 90,
            "master_path": "sub.csv",
            "errors": [],
            "status": "OK",
        },
    )
    monkeypatch.setattr(download_subawards.sys, "argv", ["download_subawards.py"])
    assert download_subawards.main() == 0

    monkeypatch.setattr(
        download_subawards,
        "_run",
        lambda force=False, fy_start=None: {
            "raw_rows": 0,
            "master_rows": 0,
            "master_path": "sub.csv",
            "errors": ["window failed"],
            "status": "EMPTY",
        },
    )
    monkeypatch.setattr(download_subawards.sys, "argv", ["download_subawards.py"])
    assert download_subawards.main() == 1

    monkeypatch.setattr(
        download_subawards.sys,
        "argv",
        ["download_subawards.py", "--allow-empty-success"],
    )
    assert download_subawards.main() == 0


def test_download_usace_main_return_flow(monkeypatch):
    monkeypatch.setattr(
        download_usace_civil,
        "_run",
        lambda force=False, fy_start=None: {
            "master_rows": 7,
            "errors": [],
            "status": "OK",
        },
    )
    monkeypatch.setattr(download_usace_civil.sys, "argv", ["download_usace_civil.py"])
    assert download_usace_civil.main() == 0

    # Endpoint errors remain nonzero without allow flag.
    monkeypatch.setattr(
        download_usace_civil,
        "_run",
        lambda force=False, fy_start=None: {
            "master_rows": 0,
            "errors": ["endpoint timeout"],
            "status": "EMPTY",
        },
    )
    monkeypatch.setattr(download_usace_civil.sys, "argv", ["download_usace_civil.py"])
    assert download_usace_civil.main() == 1

    # Endpoint errors become nonfatal only in explicit allow-empty retry mode.
    monkeypatch.setattr(
        download_usace_civil.sys,
        "argv",
        ["download_usace_civil.py", "--allow-empty-success"],
    )
    assert download_usace_civil.main() == 0

    # If there are endpoint errors but rows exist, still nonzero (not an empty retry case).
    monkeypatch.setattr(
        download_usace_civil,
        "_run",
        lambda force=False, fy_start=None: {
            "master_rows": 5,
            "errors": ["endpoint timeout"],
            "status": "OK",
        },
    )
    monkeypatch.setattr(
        download_usace_civil.sys,
        "argv",
        ["download_usace_civil.py", "--allow-empty-success"],
    )
    assert download_usace_civil.main() == 1
