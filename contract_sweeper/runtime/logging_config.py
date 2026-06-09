"""Structured logging configuration for the runtime layer.

A single, idempotent entry point (:func:`configure_logging`) so every runtime
CLI and future ingestion script emits logs in the same machine-greppable shape.
This is the resumption-readiness foundation (Wave M, task 70): when ingestion
resumes, operational events (retries, gate outcomes, manifest writes) should be
structured and filterable rather than scattered bare ``print`` calls.

Distinction worth keeping: a module's **result** — the JSON a CLI ``main()``
writes to stdout for piping — is the command's output contract and stays a
``print``. Its **diagnostics** — what happened, retries, warnings — are logs and
go through a module logger configured here (to stderr by default), so stdout
stays clean for the machine-readable result.

Format is key=value by default (greppable, no dependency); set
``CONTRACT_SWEEPER_LOG_FORMAT=json`` for line-delimited JSON. Level comes from
``CONTRACT_SWEEPER_LOG_LEVEL`` (default ``INFO``). Stdlib only; never logs secrets.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import TextIO

LEVEL_ENV = "CONTRACT_SWEEPER_LOG_LEVEL"
FORMAT_ENV = "CONTRACT_SWEEPER_LOG_FORMAT"
DEFAULT_LEVEL = "INFO"

# Marks the handler we install so configure_logging is idempotent and never
# stacks duplicate handlers on the root logger across repeated CLI invocations.
_HANDLER_FLAG = "_contract_sweeper_runtime_handler"

# Fields that logging.LogRecord always carries; everything else a caller passes
# via `extra=` is treated as a structured field and rendered into the line.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class KeyValueFormatter(logging.Formatter):
    """``ts=… level=… logger=… msg="…"`` with any ``extra=`` fields appended."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"

    def format(self, record: logging.LogRecord) -> str:
        parts = [
            f"ts={self.formatTime(record)}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg={_quote(record.getMessage())}",
        ]
        for key, value in _extra_fields(record):
            parts.append(f"{key}={_quote(str(value))}")
        if record.exc_info:
            parts.append(f"exc={_quote(self.formatException(record.exc_info))}")
        return " ".join(parts)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ``{ts, level, logger, msg, **extra}``."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in _extra_fields(record):
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _extra_fields(record: logging.LogRecord):
    for key, value in record.__dict__.items():
        if key not in _RESERVED and not key.startswith("_"):
            yield key, value


def _quote(value: str) -> str:
    """Quote a value only when it would otherwise break key=value parsing."""
    if value == "" or any(c in value for c in ' \t\n"='):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return value


def _resolve_level(level: int | str | None) -> int:
    if level is None:
        level = os.environ.get(LEVEL_ENV, DEFAULT_LEVEL)
    if isinstance(level, str):
        return logging.getLevelName(level.upper()) if level.strip() else logging.INFO
    return level


def _resolve_formatter(json_format: bool | None) -> logging.Formatter:
    if json_format is None:
        json_format = os.environ.get(FORMAT_ENV, "").strip().lower() == "json"
    return JsonFormatter() if json_format else KeyValueFormatter()


def configure_logging(
    level: int | str | None = None,
    *,
    json_format: bool | None = None,
    stream: TextIO | None = None,
    force: bool = False,
) -> logging.Logger:
    """Install a single structured handler on the root logger (idempotent).

    Returns the root logger. Safe to call from every CLI ``main()``: the first
    call configures, later calls are no-ops unless ``force=True`` (which replaces
    the handler — useful in tests). ``level``/``json_format`` override the
    ``CONTRACT_SWEEPER_LOG_*`` env vars when given explicitly.
    """
    root = logging.getLogger()
    existing = [h for h in root.handlers if getattr(h, _HANDLER_FLAG, False)]
    resolved_level = _resolve_level(level)

    if existing and not force:
        root.setLevel(resolved_level)
        return root

    for handler in existing:
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(_resolve_formatter(json_format))
    setattr(handler, _HANDLER_FLAG, True)
    root.addHandler(handler)
    root.setLevel(resolved_level)
    return root


def get_logger(name: str) -> logging.Logger:
    """Module-logger accessor — pairs with :func:`configure_logging`."""
    return logging.getLogger(name)
