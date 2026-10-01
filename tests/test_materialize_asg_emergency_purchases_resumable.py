from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import materialize_asg_emergency_purchases_resumable as mat


class _FakeSession:
    def close(self):
        pass


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def _record(control: str, vendor: str = "Vendor One (12345)", amount: str = "$10.00") -> dict:
    return {
        "Número de Control ASG": control,
        "Número Orden de Compra": f"PO-{control}",
        "Bienes o servicios a adquirir": "Item",
        "Proveedor": vendor,
        "Costo": amount,
        "Agencia": "ASG",
    }


def _wire(monkeypatch, pages: dict[int, list[dict]], declared_pages: int | dict[int, int]):
    monkeypatch.setattr(mat, "setup_logging", lambda *_: _Logger())
    monkeypatch.setattr(mat.asg, "build_session", lambda *a, **k: _FakeSession())
    monkeypatch.setattr(mat.asg, "_fetch_page", lambda _session, page, _logger: f"page:{page}" if page in pages else None)
    if isinstance(declared_pages, dict):
        monkeypatch.setattr(
            mat.asg,
            "declared_page_count",
            lambda html: declared_pages[int(html.split(":")[1])],
        )
    else:
        monkeypatch.setattr(mat.asg, "declared_page_count", lambda _html: declared_pages)
    monkeypatch.setattr(
        mat.asg,
        "parse_records",
        lambda html: pages[int(html.split(":")[1])],
    )
    monkeypatch.setattr(
        mat.asg,
        "apply_post_ingest",
        lambda frame, source_id, root: frame,
    )


@pytest.mark.unit
def test_partial_run_never_promotes_output(monkeypatch, tmp_path: Path):
    _wire(
        monkeypatch,
        {
            1: [_record("26-ASG-AAA-0001")],
            2: [_record("26-ASG-AAA-0002")],
        },
        2,
    )
    result = mat.run(tmp_path, max_pages=1, reset=True)
    assert result["status"] == "PROVISIONAL_MAX_PAGES"
    assert result["nextPage"] == 2
    assert result["pagesCompleted"] == 1
    assert not (tmp_path / mat.OUT_PATH_REL).exists()
    checkpoint, work, receipt = mat.paths(tmp_path)
    assert checkpoint.exists()
    assert work.exists()
    assert not receipt.exists()


@pytest.mark.unit
def test_resume_closes_denominator_and_promotes_once_complete(monkeypatch, tmp_path: Path):
    pages = {
        1: [_record("26-ASG-AAA-0001", "Vendor One (12345)", "$10.00")],
        2: [_record("26-ASG-AAA-0002", "Vendor Two (22222)", "$20.00")],
    }
    _wire(monkeypatch, pages, 2)
    first = mat.run(tmp_path, max_pages=1, reset=True)
    assert first["status"] == "PROVISIONAL_MAX_PAGES"

    second = mat.run(tmp_path, max_pages=None, reset=False)
    assert second["status"] == "COMPLETE"
    assert second["declaredPages"] == 2
    assert second["authoritativeUniverseTotal"] == 2
    assert second["uniqueControlNumbers"] == 2
    assert second["identityObservation"]["sourceNativeRows"] == 2

    output = tmp_path / mat.OUT_PATH_REL
    assert output.exists()
    frame = pd.read_csv(output, dtype=str)
    assert list(frame["control_number"]) == ["26-ASG-AAA-0001", "26-ASG-AAA-0002"]
    assert list(frame["vendor_registration_id"]) == ["12345", "22222"]


@pytest.mark.unit
def test_live_page_count_change_blocks_resume(monkeypatch, tmp_path: Path):
    pages = {
        1: [_record("26-ASG-AAA-0001")],
        2: [_record("26-ASG-AAA-0002")],
    }
    _wire(monkeypatch, pages, {1: 2, 2: 3})
    first = mat.run(tmp_path, max_pages=1, reset=True)
    assert first["declaredPages"] == 2

    second = mat.run(tmp_path, max_pages=None, reset=False)
    assert second["status"] == "BLOCKED_PAGE_COUNT_CHANGED"
    assert second["latestDeclaredPages"] == 3
    assert not (tmp_path / mat.OUT_PATH_REL).exists()


@pytest.mark.unit
def test_duplicate_control_number_refuses_promotion(monkeypatch, tmp_path: Path):
    pages = {
        1: [
            _record("26-ASG-AAA-0001"),
            _record("26-ASG-AAA-0002"),
        ],
        2: [
            _record("26-ASG-AAA-0001"),
            _record("26-ASG-AAA-0003"),
        ],
    }
    _wire(monkeypatch, pages, 2)
    with pytest.raises(RuntimeError, match="duplicate control_number"):
        mat.run(tmp_path, max_pages=None, reset=True)
    assert not (tmp_path / mat.OUT_PATH_REL).exists()


@pytest.mark.unit
def test_tampered_work_file_invalidates_resume(monkeypatch, tmp_path: Path):
    _wire(
        monkeypatch,
        {
            1: [_record("26-ASG-AAA-0001")],
            2: [_record("26-ASG-AAA-0002")],
        },
        2,
    )
    first = mat.run(tmp_path, max_pages=1, reset=True)
    assert first["status"] == "PROVISIONAL_MAX_PAGES"
    _, work, _ = mat.paths(tmp_path)
    work.write_text(work.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        mat.run(tmp_path, max_pages=None, reset=False)
