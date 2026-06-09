"""Tests for the runtime structured-logging foundation (Wave M, task 70)."""

from __future__ import annotations

import io
import json
import logging

import pytest

from contract_sweeper.runtime import logging_config as lc


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot/restore the root logger so tests don't leak handlers."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def _capture(logger_name="cslog.kv", **kwargs) -> tuple[io.StringIO, logging.Logger]:
    stream = io.StringIO()
    lc.configure_logging(stream=stream, force=True, **kwargs)
    return stream, lc.get_logger(logger_name)


@pytest.mark.unit
def test_key_value_format_has_core_fields():
    stream, log = _capture()
    log.info("hello world")
    line = stream.getvalue().strip()
    assert "level=INFO" in line
    assert "logger=cslog.kv" in line
    # The message contains a space, so it must be quoted.
    assert 'msg="hello world"' in line
    assert line.startswith("ts=")


@pytest.mark.unit
def test_extra_fields_are_rendered_as_key_values():
    stream, log = _capture()
    log.warning("gate", extra={"gate": "coverage", "status": "FAIL"})
    line = stream.getvalue().strip()
    assert "gate=coverage" in line
    assert "status=FAIL" in line
    assert "level=WARNING" in line


@pytest.mark.unit
def test_unquoted_simple_value_quoted_complex_value():
    stream, log = _capture()
    log.info("plain", extra={"simple": "ok", "complex": "a b=c"})
    line = stream.getvalue().strip()
    assert "simple=ok" in line  # no spaces/specials → unquoted
    assert 'complex="a b=c"' in line  # space and '=' → quoted


@pytest.mark.unit
def test_json_format_emits_one_object_per_line():
    stream, log = _capture(json_format=True)
    log.info("ingest", extra={"rows": 42, "source": "fec"})
    payload = json.loads(stream.getvalue().strip())
    assert payload["level"] == "INFO"
    assert payload["msg"] == "ingest"
    assert payload["rows"] == 42
    assert payload["source"] == "fec"
    assert payload["logger"] == "cslog.kv"


@pytest.mark.unit
def test_exception_info_is_captured():
    stream, log = _capture(json_format=True)
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed")
    payload = json.loads(stream.getvalue().strip())
    assert "ValueError: boom" in payload["exc"]


@pytest.mark.unit
def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    lc.configure_logging(force=True)
    count_after_first = sum(1 for h in root.handlers if getattr(h, lc._HANDLER_FLAG, False))
    lc.configure_logging()  # no force → must not add another handler
    lc.configure_logging()
    count_after_repeat = sum(1 for h in root.handlers if getattr(h, lc._HANDLER_FLAG, False))
    assert count_after_first == 1
    assert count_after_repeat == 1


@pytest.mark.unit
def test_force_replaces_rather_than_stacks_handler():
    root = logging.getLogger()
    lc.configure_logging(force=True)
    lc.configure_logging(force=True)
    flagged = [h for h in root.handlers if getattr(h, lc._HANDLER_FLAG, False)]
    assert len(flagged) == 1


@pytest.mark.unit
def test_level_from_env(monkeypatch):
    monkeypatch.setenv(lc.LEVEL_ENV, "WARNING")
    stream = io.StringIO()
    lc.configure_logging(stream=stream, force=True)
    log = lc.get_logger("cslog.level")
    log.info("suppressed")
    log.warning("shown")
    out = stream.getvalue()
    assert "suppressed" not in out
    assert "shown" in out


@pytest.mark.unit
def test_format_from_env(monkeypatch):
    monkeypatch.setenv(lc.FORMAT_ENV, "json")
    stream = io.StringIO()
    lc.configure_logging(stream=stream, force=True)
    lc.get_logger("cslog.fmt").info("via-env")
    json.loads(stream.getvalue().strip())  # must parse as JSON


@pytest.mark.unit
def test_explicit_level_overrides_env(monkeypatch):
    monkeypatch.setenv(lc.LEVEL_ENV, "ERROR")
    stream = io.StringIO()
    lc.configure_logging(level="DEBUG", stream=stream, force=True)
    lc.get_logger("cslog.override").debug("debug-shown")
    assert "debug-shown" in stream.getvalue()
