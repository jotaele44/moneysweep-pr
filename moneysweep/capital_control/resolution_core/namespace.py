from __future__ import annotations

from dataclasses import dataclass

from .models import CertificationState, NamespaceBinding


@dataclass(frozen=True)
class NamespaceOccupancyResult:
    state: CertificationState
    binding: NamespaceBinding | None
    conflict: NamespaceBinding | None
    reason: str


class NamespaceRegistry:
    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], NamespaceBinding] = {}

    def register(self, binding: NamespaceBinding) -> NamespaceOccupancyResult:
        key = (binding.namespace, binding.identifier)
        existing = self._bindings.get(key)
        if existing is None:
            self._bindings[key] = binding
            return NamespaceOccupancyResult(
                CertificationState.PASS, binding, None, "identifier registered"
            )
        if existing.subject_ref == binding.subject_ref:
            return NamespaceOccupancyResult(
                CertificationState.PASS,
                existing,
                None,
                "same subject already occupies identifier",
            )
        return NamespaceOccupancyResult(
            CertificationState.FAIL,
            None,
            existing,
            f"identifier already occupied by {existing.subject_ref}",
        )

    def lookup(self, namespace: str, identifier: str) -> NamespaceBinding | None:
        return self._bindings.get((namespace, identifier))
