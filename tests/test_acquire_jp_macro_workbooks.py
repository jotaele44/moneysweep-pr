from __future__ import annotations

import io
import json
from pathlib import Path
from zipfile import ZipFile

from scripts.acquire_jp_macro_workbooks import acquire_all, acquire_one


def _xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content: bytes, *, status_error: Exception | None = None) -> None:
        self.content = content
        self.headers = {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "ETag": '"fixture"',
        }
        self.url = "https://example.test/resolved.xlsx"
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def _source() -> dict[str, str]:
    return {
        "id": "JP_IP_2025_XLSX",
        "title": "Fixture",
        "url": "https://example.test/a.xlsx",
    }


def test_acquire_one_freezes_exact_bytes_headers_and_hash(tmp_path: Path) -> None:
    data = _xlsx_bytes()
    session = FakeSession(FakeResponse(data))

    result = acquire_one(_source(), tmp_path, session=session)

    raw = Path(result["path"])
    assert raw.read_bytes() == data
    assert result["size_bytes"] == len(data)
    assert len(result["sha256"]) == 64
    assert result["state"] == "BYTE_FROZEN"
    headers = json.loads(Path(result["response_headers_path"]).read_text(encoding="utf-8"))
    assert headers["ETag"] == '"fixture"'
    assert session.calls[0]["allow_redirects"] is True


def test_acquire_one_rejects_non_xlsx_payload(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(b"<html>not an xlsx</html>"))

    try:
        acquire_one(_source(), tmp_path, session=session)
    except ValueError as exc:
        assert "not a ZIP/XLSX" in str(exc)
    else:
        raise AssertionError("non-XLSX response must fail closed")


def test_acquire_all_preserves_failures_as_blocked_not_absent(tmp_path: Path) -> None:
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps({"mandatory_workbooks": [_source()]}),
        encoding="utf-8",
    )
    session = FakeSession(FakeResponse(b"not-a-workbook"))
    out = tmp_path / "snapshot"

    result = acquire_all(manifest, out, session=session)

    assert result["complete"] is False
    assert result["frozen_count"] == 0
    assert result["failure_count"] == 1
    assert result["failures"][0]["state"] == "RETRIEVAL_BLOCKED_NOT_SOURCE_ABSENT"
    written = json.loads((out / "source_manifest.json").read_text(encoding="utf-8"))
    assert written["failures"][0]["state"] == "RETRIEVAL_BLOCKED_NOT_SOURCE_ABSENT"
