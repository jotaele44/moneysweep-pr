"""Temporal ownership and control intervals.

An unknown holder is recorded as unknown. Equity, beneficial ownership, control
and operating rights are separate interest kinds and are never traversed as one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from moneysweep.capital_control.resolution_core import CertificationState, EvidenceBasis

from ._common import (
    FinancialIntelligenceError,
    active_on,
    check_interval,
    check_temporal_scope,
    promotable,
    require_text,
)


class InterestKind(str, Enum):
    LEGAL_TITLE = "LEGAL_TITLE"
    EQUITY = "EQUITY"
    BENEFICIAL = "BENEFICIAL"
    CONTROL = "CONTROL"
    OPERATING_RIGHT = "OPERATING_RIGHT"


class Terminal(str, Enum):
    NO_FURTHER_RECORD = "NO_FURTHER_RECORD"
    UNRESOLVED = "UNRESOLVED"


def _share(value: str | None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FinancialIntelligenceError("share must be an exact decimal string")
    try:
        share = Decimal(value)
    except InvalidOperation as exc:
        raise FinancialIntelligenceError("invalid share") from exc
    if not share.is_finite() or share <= 0 or share > 1:
        raise FinancialIntelligenceError("share must be greater than 0 and at most 1")
    return share


@dataclass(frozen=True)
class OwnershipInterval:
    """A dated, sourced interest held in a subject (entity or asset)."""

    interval_id: str
    subject_ref: str
    holder_ref: str | None
    kind: InterestKind
    source_manifestation_id: str
    share: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    state: CertificationState = CertificationState.UNRESOLVED
    pre_baseline_justification: str | None = None

    def __post_init__(self) -> None:
        require_text(self.interval_id, "interval_id")
        require_text(self.subject_ref, "subject_ref")
        require_text(self.source_manifestation_id, "source_manifestation_id")
        if self.holder_ref is None:
            if self.state is CertificationState.PASS:
                raise FinancialIntelligenceError("an unknown holder cannot be certified")
        else:
            require_text(self.holder_ref, "holder_ref")
            if self.holder_ref == self.subject_ref:
                raise FinancialIntelligenceError("a subject cannot hold an interest in itself")
        _share(self.share)
        check_interval(self.valid_from, self.valid_to)
        check_temporal_scope(self.valid_from, self.pre_baseline_justification, "valid_from")


@dataclass(frozen=True)
class HolderPath:
    """One chain from the subject upward. `holder_ref` is None when unresolved."""

    holder_ref: str | None
    interval_ids: tuple[str, ...]
    effective_share: str | None
    terminal: Terminal


def _index(intervals: Iterable[OwnershipInterval]) -> list[OwnershipInterval]:
    seen: set[str] = set()
    items = list(intervals)
    for interval in items:
        if interval.interval_id in seen:
            raise FinancialIntelligenceError("duplicate ownership interval")
        seen.add(interval.interval_id)
    return items


def holders_at(
    intervals: Iterable[OwnershipInterval], subject_ref: str, on: str, kind: InterestKind
) -> tuple[OwnershipInterval, ...]:
    """Every interval of one kind whose known bounds include the date, promoted or not."""
    return tuple(
        interval
        for interval in _index(intervals)
        if interval.subject_ref == subject_ref
        and interval.kind is kind
        and active_on(interval.valid_from, interval.valid_to, on)
    )


def assert_share_conservation(
    intervals: Iterable[OwnershipInterval], subject_ref: str, on: str, kind: InterestKind
) -> Decimal:
    """Certified shares of one kind on one date cannot exceed the whole."""
    total = Decimal(0)
    for interval in holders_at(intervals, subject_ref, on, kind):
        share = _share(interval.share)
        if share is not None and promotable(interval.evidence_basis, interval.state):
            total += share
    if total > 1:
        raise FinancialIntelligenceError(
            f"certified {kind.value} shares in {subject_ref} exceed 100% on {on}"
        )
    return total


def resolve_ultimate_holders(
    intervals: Iterable[OwnershipInterval],
    subject_ref: str,
    on: str,
    kind: InterestKind = InterestKind.EQUITY,
    max_depth: int = 32,
) -> tuple[HolderPath, ...]:
    """Walk one interest kind upward through certified intervals only.

    A chain ends as UNRESOLVED at an unknown holder or an uncertified link, and
    as NO_FURTHER_RECORD when the corpus holds nothing above a holder. Neither
    is a claim that the last holder is the ultimate owner in the world.
    """
    corpus = _index(intervals)
    paths: list[HolderPath] = []

    def walk(
        subject: str, trail: tuple[str, ...], share: Decimal | None, visited: tuple[str, ...]
    ) -> None:
        if len(trail) > max_depth:
            raise FinancialIntelligenceError("ownership chain exceeds the depth limit")
        links = [
            interval
            for interval in corpus
            if interval.subject_ref == subject
            and interval.kind is kind
            and active_on(interval.valid_from, interval.valid_to, on)
        ]
        if not links:
            if trail:
                paths.append(
                    HolderPath(
                        holder_ref=subject,
                        interval_ids=trail,
                        effective_share=None if share is None else format(share, "f"),
                        terminal=Terminal.NO_FURTHER_RECORD,
                    )
                )
            return
        for link in sorted(links, key=lambda item: item.interval_id):
            next_trail = trail + (link.interval_id,)
            link_share = _share(link.share)
            next_share = None if share is None or link_share is None else share * link_share
            if link.holder_ref is None or not promotable(link.evidence_basis, link.state):
                paths.append(
                    HolderPath(
                        holder_ref=None,
                        interval_ids=next_trail,
                        effective_share=None,
                        terminal=Terminal.UNRESOLVED,
                    )
                )
                continue
            if link.holder_ref in visited:
                raise FinancialIntelligenceError("circular ownership requires adjudication")
            walk(link.holder_ref, next_trail, next_share, visited + (link.holder_ref,))

    walk(subject_ref, (), Decimal(1), (subject_ref,))
    return tuple(paths)
