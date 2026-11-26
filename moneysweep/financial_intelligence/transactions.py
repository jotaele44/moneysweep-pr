"""Canonical transaction identity and N:N domain projection.

One underlying transaction has one identity however many analytical domains it
appears in. Domain membership is evidenced separately and never changes the
identity, so totals are computed over unique transactions, not over domain views.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from moneysweep.capital_control.resolution_core import CertificationState, EvidenceBasis
from moneysweep.financial_classification_v1 import (
    SHA_PATTERN,
    ObservationError,
    canonical_bytes,
    decimal_string,
)

from ._common import (
    FinancialIntelligenceError,
    check_temporal_scope,
    parse_date,
    promotable,
    require_text,
)

PUERTO_RICO = "PR"
ID_PREFIX = "mstx_"


class FlowDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    INTERNAL = "INTERNAL"
    UNRESOLVED = "UNRESOLVED"
    NO_PR_NEXUS = "NO_PR_NEXUS"


class FlowCharacter(str, Enum):
    PASS_THROUGH = "PASS_THROUGH"
    RETAINED = "RETAINED"
    EXTRACTED = "EXTRACTED"
    NONCASH = "NONCASH"
    CONTINGENT = "CONTINGENT"


NON_CASH_CHARACTERS = frozenset({FlowCharacter.NONCASH, FlowCharacter.CONTINGENT})


class Disclosure(str, Enum):
    DISCLOSED = "DISCLOSED"
    PARTIALLY_DISCLOSED = "PARTIALLY_DISCLOSED"
    CONFIDENTIAL = "CONFIDENTIAL"
    UNDISCLOSED = "UNDISCLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Transaction:
    """One source-native transaction. Unknown parties and amounts stay None."""

    transaction_id: str
    source_id: str
    source_record_id: str
    event_type: str
    source_sha256: str
    source_version: str
    event_date: str | None
    origin_ref: str | None
    destination_ref: str | None
    amount_decimal: str | None
    currency: str | None
    valuation_basis: str | None
    disclosure: Disclosure
    state: CertificationState


def transaction_id(source_id: str, source_record_id: str, event_type: str) -> str:
    """Deterministic identity from the source-native record, not from its content.

    The file hash, amount, date, parties and domains are deliberately excluded:
    a re-retrieved snapshot or a new domain view is the same transaction.
    """
    payload = {
        "source_id": require_text(source_id, "source_id"),
        "source_record_id": require_text(source_record_id, "source_record_id"),
        "event_type": require_text(event_type, "event_type"),
    }
    return ID_PREFIX + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def make_transaction(
    *,
    source_id: str,
    source_record_id: str,
    event_type: str,
    source_sha256: str,
    source_version: str = "1",
    event_date: str | None = None,
    origin_ref: str | None = None,
    destination_ref: str | None = None,
    amount: str | int | None = None,
    currency: str | None = None,
    valuation_basis: str | None = None,
    disclosure: Disclosure = Disclosure.UNKNOWN,
    state: CertificationState = CertificationState.UNRESOLVED,
    pre_baseline_justification: str | None = None,
) -> Transaction:
    identity = transaction_id(source_id, source_record_id, event_type)
    if not SHA_PATTERN.fullmatch(source_sha256 or ""):
        raise FinancialIntelligenceError("source_sha256 must be lowercase SHA256")
    require_text(source_version, "source_version")
    parse_date(event_date, "event_date")
    check_temporal_scope(event_date, pre_baseline_justification, "event_date")
    for ref, field in ((origin_ref, "origin_ref"), (destination_ref, "destination_ref")):
        if ref is not None:
            require_text(ref, field)

    amount_decimal: str | None = None
    if amount is None:
        if disclosure is Disclosure.DISCLOSED:
            raise FinancialIntelligenceError(
                "an absent amount must record its disclosure limitation"
            )
        if currency is not None or valuation_basis is not None:
            raise FinancialIntelligenceError("an absent amount carries no currency or basis")
    else:
        try:
            amount_decimal = decimal_string(amount)
        except ObservationError as exc:
            raise FinancialIntelligenceError(str(exc)) from exc
        if Decimal(amount_decimal) < 0:
            raise FinancialIntelligenceError(
                "amount cannot be negative; record a reversal as its own event"
            )
        if currency is None or len(currency) != 3 or currency != currency.upper():
            raise FinancialIntelligenceError("known amount requires a three-letter currency")
        require_text(valuation_basis, "valuation_basis")
        if disclosure not in {Disclosure.DISCLOSED, Disclosure.PARTIALLY_DISCLOSED}:
            raise FinancialIntelligenceError("a known amount is at least partially disclosed")

    return Transaction(
        transaction_id=identity,
        source_id=source_id,
        source_record_id=source_record_id,
        event_type=event_type,
        source_sha256=source_sha256,
        source_version=source_version,
        event_date=event_date,
        origin_ref=origin_ref,
        destination_ref=destination_ref,
        amount_decimal=amount_decimal,
        currency=currency,
        valuation_basis=valuation_basis,
        disclosure=disclosure,
        state=state,
    )


def geographic_direction(
    origin_jurisdiction: str | None, destination_jurisdiction: str | None
) -> FlowDirection:
    """Direction relative to Puerto Rico from resolved party jurisdictions only.

    The US mainland is external to Puerto Rico for this purpose. An unknown
    jurisdiction yields UNRESOLVED; it is never defaulted to local or foreign.
    """
    if not origin_jurisdiction or not destination_jurisdiction:
        return FlowDirection.UNRESOLVED
    origin_local = origin_jurisdiction == PUERTO_RICO
    destination_local = destination_jurisdiction == PUERTO_RICO
    if origin_local and destination_local:
        return FlowDirection.INTERNAL
    if destination_local:
        return FlowDirection.INBOUND
    if origin_local:
        return FlowDirection.OUTBOUND
    return FlowDirection.NO_PR_NEXUS


@dataclass(frozen=True)
class DomainMembership:
    """Evidence that a transaction belongs in one analytical domain."""

    transaction_id: str
    domain_id: str
    source_manifestation_id: str
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    state: CertificationState = CertificationState.UNRESOLVED

    def __post_init__(self) -> None:
        require_text(self.transaction_id, "transaction_id")
        require_text(self.domain_id, "domain_id")
        require_text(self.source_manifestation_id, "source_manifestation_id")


@dataclass(frozen=True)
class FlowCharacterAssertion:
    """Evidence that a transaction is pass-through, retained, extracted, noncash or contingent."""

    transaction_id: str
    character: FlowCharacter
    source_manifestation_id: str
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    state: CertificationState = CertificationState.UNRESOLVED

    def __post_init__(self) -> None:
        require_text(self.transaction_id, "transaction_id")
        require_text(self.source_manifestation_id, "source_manifestation_id")


@dataclass(frozen=True)
class TransactionEquivalence:
    """A claim that two source-native transactions are one underlying transaction."""

    left_id: str
    right_id: str
    source_manifestation_id: str
    evidence_basis: EvidenceBasis = EvidenceBasis.NONE
    state: CertificationState = CertificationState.UNRESOLVED

    def __post_init__(self) -> None:
        if self.left_id == self.right_id:
            raise FinancialIntelligenceError("a transaction is trivially equivalent to itself")
        require_text(self.source_manifestation_id, "source_manifestation_id")


def index_transactions(transactions: Iterable[Transaction]) -> dict[str, Transaction]:
    """Index by identity; the same identity with different content fails closed."""
    index: dict[str, Transaction] = {}
    for transaction in transactions:
        previous = index.get(transaction.transaction_id)
        if previous is not None and previous != transaction:
            raise FinancialIntelligenceError(
                "one transaction identity carries conflicting manifestations"
            )
        index[transaction.transaction_id] = transaction
    return index


def validate_memberships(
    memberships: Iterable[DomainMembership],
    transactions: Iterable[Transaction],
    domain_ids: Iterable[str],
) -> None:
    known_transactions = set(index_transactions(transactions))
    known_domains = set(domain_ids)
    seen: set[tuple[str, str, str]] = set()
    for membership in memberships:
        if membership.transaction_id not in known_transactions:
            raise FinancialIntelligenceError("membership references an unknown transaction")
        if membership.domain_id not in known_domains:
            raise FinancialIntelligenceError(f"unknown domain {membership.domain_id}")
        key = (membership.transaction_id, membership.domain_id, membership.source_manifestation_id)
        if key in seen:
            raise FinancialIntelligenceError("duplicate domain-membership observation")
        seen.add(key)


def project_domains(
    memberships: Iterable[DomainMembership], *, promoted_only: bool = True
) -> dict[str, frozenset[str]]:
    """Domain -> transaction identities. Unevidenced memberships are left out by default."""
    views: defaultdict[str, set[str]] = defaultdict(set)
    for membership in memberships:
        if promoted_only and not promotable(membership.evidence_basis, membership.state):
            continue
        views[membership.domain_id].add(membership.transaction_id)
    return {domain: frozenset(ids) for domain, ids in views.items()}


def canonical_ids(
    transactions: Iterable[Transaction], equivalences: Iterable[TransactionEquivalence] = ()
) -> dict[str, str]:
    """Map each transaction to its canonical identity.

    Only a PASS equivalence on binding evidence merges two identities. Matching
    amounts, dates or party names are never an equivalence.
    """
    index = index_transactions(transactions)
    parent = {identity: identity for identity in index}

    def find(identity: str) -> str:
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    for equivalence in equivalences:
        if equivalence.left_id not in index or equivalence.right_id not in index:
            raise FinancialIntelligenceError("equivalence references an unknown transaction")
        if not promotable(equivalence.evidence_basis, equivalence.state):
            continue
        left, right = find(equivalence.left_id), find(equivalence.right_id)
        if left != right:
            parent[max(left, right)] = min(left, right)
    return {identity: find(identity) for identity in index}


def non_cash_ids(characters: Iterable[FlowCharacterAssertion]) -> frozenset[str]:
    """Transactions with any noncash or contingent claim, promoted or not.

    An unadjudicated claim is enough to keep a transaction out of a cash total.
    """
    return frozenset(c.transaction_id for c in characters if c.character in NON_CASH_CHARACTERS)


def character_conflicts(characters: Iterable[FlowCharacterAssertion]) -> frozenset[str]:
    """Transactions asserted as both retained and extracted on promotable evidence."""
    held: defaultdict[str, set[FlowCharacter]] = defaultdict(set)
    for assertion in characters:
        if promotable(assertion.evidence_basis, assertion.state):
            held[assertion.transaction_id].add(assertion.character)
    pair = {FlowCharacter.RETAINED, FlowCharacter.EXTRACTED}
    return frozenset(identity for identity, found in held.items() if pair <= found)


def unique_total(
    transactions: Iterable[Transaction],
    *,
    equivalences: Iterable[TransactionEquivalence] = (),
    characters: Iterable[FlowCharacterAssertion] = (),
) -> dict[str, object]:
    """Cash total over unique underlying transactions; fail closed on mixed bases."""
    index = index_transactions(transactions)
    canonical = canonical_ids(index.values(), equivalences)
    excluded_non_cash = non_cash_ids(characters) & set(index)

    groups: defaultdict[str, list[Transaction]] = defaultdict(list)
    for identity, transaction in index.items():
        groups[canonical[identity]].append(transaction)

    total = Decimal(0)
    bases: set[tuple[str | None, str | None]] = set()
    counted = unknown_amount = non_cash = 0
    for members in groups.values():
        if any(member.transaction_id in excluded_non_cash for member in members):
            non_cash += 1
            continue
        known = {
            (member.amount_decimal, member.currency, member.valuation_basis)
            for member in members
            if member.amount_decimal is not None
        }
        if not known:
            unknown_amount += 1
            continue
        normalized = {(Decimal(amount), currency, basis) for amount, currency, basis in known}
        if len(normalized) != 1:
            raise FinancialIntelligenceError(
                "equivalent transactions disagree on amount, currency or valuation basis"
            )
        amount, currency, basis = next(iter(normalized))
        bases.add((currency, basis))
        total += amount
        counted += 1
    if len(bases) > 1:
        raise FinancialIntelligenceError(
            "amounts in different currencies or valuation bases cannot be summed"
        )
    currency, basis = next(iter(bases)) if bases else (None, None)
    return {
        "amount_decimal": format(total, "f") if counted else None,
        "currency": currency,
        "valuation_basis": basis,
        "unique_transactions": len(groups),
        "counted": counted,
        "excluded_unknown_amount": unknown_amount,
        "excluded_non_cash": non_cash,
    }


def domain_rollup(
    transactions: Iterable[Transaction],
    memberships: Iterable[DomainMembership],
    *,
    equivalences: Iterable[TransactionEquivalence] = (),
    characters: Iterable[FlowCharacterAssertion] = (),
) -> dict[str, object]:
    """Per-domain totals plus the one unique total they must never be summed into."""
    index = index_transactions(transactions)
    equivalence_list = list(equivalences)
    character_list = list(characters)
    canonical = canonical_ids(index.values(), equivalence_list)
    views = project_domains(memberships)

    def restrict(ids: frozenset[str]) -> list[Transaction]:
        wanted = {canonical[i] for i in ids if i in canonical}
        return [t for i, t in index.items() if canonical[i] in wanted]

    def total(ids: frozenset[str]) -> dict[str, object]:
        subset = restrict(ids)
        subset_ids = {t.transaction_id for t in subset}
        return unique_total(
            subset,
            equivalences=[
                e for e in equivalence_list if e.left_id in subset_ids and e.right_id in subset_ids
            ],
            characters=character_list,
        )

    appearances: defaultdict[str, int] = defaultdict(int)
    for ids in views.values():
        for canonical_id in {canonical[i] for i in ids if i in canonical}:
            appearances[canonical_id] += 1
    return {
        "domains": {domain: total(ids) for domain, ids in sorted(views.items())},
        "unique_total": unique_total(
            index.values(), equivalences=equivalence_list, characters=character_list
        ),
        "transactions_in_multiple_domains": sum(1 for n in appearances.values() if n > 1),
        "domain_totals_are_additive": False,
    }
