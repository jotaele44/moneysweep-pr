"""Interrupted research pagination must not publish a partial normal cache."""

import logging
from unittest.mock import Mock

import pytest
import requests

from scripts import download_research as research


@pytest.mark.parametrize("agency", ["nih", "nsf"])
@pytest.mark.parametrize("failure", ["transport", "json", "http", "schema"])
def test_later_page_failure_preserves_cache(tmp_path, monkeypatch, agency, failure):
    monkeypatch.setattr(research, f"{agency.upper()}_PAGE_SIZE", 1)
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    cache = research._raw_research_dir(tmp_path) / f"{agency}_raw.csv"
    original = b"prior,frozen\nsource,bytes\n"
    cache.write_bytes(original)
    first = Mock()
    first.json.return_value = (
        {"meta": {"total": 2}, "results": [{"project_num": "P1"}]}
        if agency == "nih"
        else {"response": {"@status": "OK", "award": [{"id": "1"}]}}
    )
    second = Mock()
    if failure == "transport":
        second = requests.ConnectionError("interrupted")
    elif failure == "json":
        second.json.side_effect = ValueError("invalid JSON")
    elif failure == "http":
        second.raise_for_status.side_effect = requests.HTTPError("upstream failure")
    else:
        second.json.return_value = (
            {"meta": {"total": 2}, "results": []}
            if agency == "nih"
            else {"response": {"@status": "ERROR"}}
        )
    request = Mock(side_effect=[first, second])
    monkeypatch.setattr(research.requests, "post" if agency == "nih" else "get", request)
    with pytest.raises(RuntimeError, match="incomplete"):
        getattr(research, f"download_{agency}")(tmp_path, True, logging.getLogger(__name__))
    assert cache.read_bytes() == original
    assert request.call_count == 2


@pytest.mark.parametrize("agency", ["nih", "nsf"])
def test_complete_download_is_cached_and_reused(tmp_path, monkeypatch, agency):
    response = Mock()
    response.json.return_value = (
        {"meta": {"total": 1}, "results": [{"project_num": "P1"}]}
        if agency == "nih"
        else {"response": {"@status": "OK", "award": [{"id": "1"}]}}
    )
    request = Mock(return_value=response)
    monkeypatch.setattr(research.requests, "post" if agency == "nih" else "get", request)
    download = getattr(research, f"download_{agency}")
    frame = download(tmp_path, True, logging.getLogger(__name__))
    assert len(frame) == 1
    cached = download(tmp_path, False, logging.getLogger(__name__))
    assert cached["award_id"].tolist() == frame["award_id"].tolist()
    assert request.call_count == 1


@pytest.mark.parametrize("total", [None, True, -1, "1", 0, 2])
def test_nih_rejects_invalid_or_inconsistent_total(tmp_path, monkeypatch, total):
    response = Mock()
    response.json.return_value = {"meta": {"total": total}, "results": [{"project_num": "P1"}]}
    monkeypatch.setattr(research.requests, "post", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="incomplete"):
        research.download_nih(tmp_path, True, logging.getLogger(__name__))
    assert not (research._raw_research_dir(tmp_path) / "nih_raw.csv").exists()


def test_cache_serialization_failure_preserves_old_file(tmp_path):
    path = tmp_path / "cache.csv"
    path.write_bytes(b"preserved")
    frame = Mock()

    def fail_after_partial_write(destination, **kwargs):
        destination.write_bytes(b"truncated")
        raise OSError("disk write failed")

    frame.to_csv.side_effect = fail_after_partial_write
    with pytest.raises(OSError, match="disk write failed"):
        research._write_cache_atomic(frame, path)
    assert path.read_bytes() == b"preserved"
    assert list(tmp_path.iterdir()) == [path]


def test_nih_total_change_preserves_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "NIH_PAGE_SIZE", 1)
    monkeypatch.setattr(research.time, "sleep", lambda _: None)
    pages = []
    for total in [2, 3]:
        response = Mock()
        response.json.return_value = {
            "meta": {"total": total},
            "results": [{"project_num": str(total)}],
        }
        pages.append(response)
    monkeypatch.setattr(research.requests, "post", Mock(side_effect=pages))
    with pytest.raises(RuntimeError, match="total changed"):
        research.download_nih(tmp_path, True, logging.getLogger(__name__))
    assert not (research._raw_research_dir(tmp_path) / "nih_raw.csv").exists()
