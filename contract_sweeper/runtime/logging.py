"""Runtime-safe logging configuration with secret redaction."""

from __future__ import annotations

import logging
import re


_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*([A-Za-z0-9_\-./]{6,})"
)


class SecretRedactionFilter(logging.Filter):
    """Redact obvious credential-like values from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        sanitized = _SECRET_RE.sub(r"\1=[REDACTED]", message)
        if sanitized != message:
            record.msg = sanitized
            record.args = ()
        return True


def configure_logging(level: str = "INFO", logger_name: str = "contract_sweeper") -> logging.Logger:
    """Create or update a logger with secret redaction and fixed formatting."""

    logger = logging.getLogger(logger_name)
    logger.setLevel(level.upper())

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%SZ",
            )
        )
        logger.addHandler(handler)

    has_filter = any(isinstance(f, SecretRedactionFilter) for f in logger.filters)
    if not has_filter:
        logger.addFilter(SecretRedactionFilter())

    logger.propagate = False
    return logger
