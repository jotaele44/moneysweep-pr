"""ID namespacing for the Contract-Sweeper producer.

Every exported ID is prefixed with ``contract_sweeper:`` so that records can be
joined across producers without collision (e.g. both repos may emit ``src_*``).
Namespacing is idempotent: re-applying it to an already-namespaced ID is a
no-op.
"""
from __future__ import annotations

PRODUCER = "contract-sweeper"
PREFIX = "contract_sweeper"


def namespaced_id(raw: object, prefix: str = PREFIX) -> str:
    """Return ``<prefix>:<raw>``; idempotent if already prefixed."""
    if raw is None:
        raise ValueError("cannot namespace a null id")
    s = str(raw).strip()
    if not s:
        raise ValueError("cannot namespace an empty id")
    token = f"{prefix}:"
    if s.startswith(token):
        return s
    return f"{prefix}:{s}"


def is_namespaced(value: object, prefix: str = PREFIX) -> bool:
    """True if ``value`` carries the ``<prefix>:`` namespace and a body."""
    token = f"{prefix}:"
    return isinstance(value, str) and value.startswith(token) and len(value) > len(token)
