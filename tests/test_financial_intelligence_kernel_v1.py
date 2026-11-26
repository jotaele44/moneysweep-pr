"""Positive and adversarial cases for the financial-intelligence candidate kernel.

Each failure mode in docs/FINANCIAL_ECONOMIC_INTELLIGENCE_SCOPE_V1.md names the
test here that guards it.
"""

from decimal import Decimal

import pytest

from moneysweep.capital_control.resolution_core import CertificationState, EvidenceBasis
from moneysweep.financial_intelligence import (
    CONFLICT,
    UNKNOWN,
    ContinuityObservation,
    Disclosure,
    DomainMembership,
    FinancialIntelligenceError,
    FlowCharacter,
    FlowCharacterAssertion,
    FlowDirection,
    InterestKind,
    OwnershipInterval,
    Terminal,
    TransactionEquivalence,
    assert_share_conservation,
    canonical_ids,
    character_conflicts,
    continuity_profile,
    domain_rollup,
    geographic_direction,
    holders_at,
    make_transaction,
    project_domains,
    resolve_ultimate_holders,
    transaction_id,
    unique_total,
    validate_memberships,
)

SHA = "a" * 64
PASS = dict(evidence_basis=EvidenceBasis.STABLE_ID, state=CertificationState.PASS)
DOMAINS = [f"MS{n:02d}" for n in range(1, 26)]


def tx(record="row-1", amount="100.00", source="official:deals", **overrides):
    fields = dict(
        source_id=source,
        source_record_id=record,
        event_type="ACQUISITION",
        source_sha256=SHA,
        amount=amount,
        currency="USD" if amount is not None else None,
        valuation_basis="disclosed_purchase_price" if amount is not None else None,
        disclosure=Disclosure.DISCLOSED if amount is not None else Disclosure.UNDISCLOSED,
    )
    fields.update(overrides)
    return make_transaction(**fields)


def member(transaction, domain, manifestation="m1", **evidence):
    return DomainMembership(transaction.transaction_id, domain, manifestation, **evidence)


# --- transaction identity ----------------------------------------------------


def test_identity_ignores_snapshot_amount_and_domains():
    first = tx()
    again = tx(source_sha256="b" * 64, amount="250.00", source_version="2")
    assert first.transaction_id == again.transaction_id
    assert first.transaction_id == transaction_id("official:deals", "row-1", "ACQUISITION")
    assert first.transaction_id.startswith("mstx_")
    assert tx(record="row-2").transaction_id != first.transaction_id
    assert tx(event_type="DIVESTMENT").transaction_id != first.transaction_id


def test_one_transaction_in_five_domains_is_counted_once():
    deal = tx()
    five = ["MS07", "MS08", "MS10", "MS16", "MS17"]
    memberships = [member(deal, domain, **PASS) for domain in five]
    validate_memberships(memberships, [deal], DOMAINS)

    rollup = domain_rollup([deal], memberships)
    assert set(rollup["domains"]) == set(five)
    assert all(view["amount_decimal"] == "100.00" for view in rollup["domains"].values())
    assert rollup["unique_total"]["amount_decimal"] == "100.00"
    assert rollup["unique_total"]["unique_transactions"] == 1
    assert rollup["transactions_in_multiple_domains"] == 1
    assert rollup["domain_totals_are_additive"] is False


def test_unevidenced_membership_is_not_projected():
    deal = tx()
    claimed = [member(deal, "MS08"), member(deal, "MS07", **PASS)]
    assert project_domains(claimed) == {"MS07": frozenset({deal.transaction_id})}
    assert set(project_domains(claimed, promoted_only=False)) == {"MS07", "MS08"}


def test_membership_batch_gates():
    deal = tx()
    with pytest.raises(FinancialIntelligenceError, match="unknown transaction"):
        validate_memberships([DomainMembership("mstx_missing", "MS08", "m1")], [deal], DOMAINS)
    with pytest.raises(FinancialIntelligenceError, match="unknown domain"):
        validate_memberships([member(deal, "MS99")], [deal], DOMAINS)
    with pytest.raises(FinancialIntelligenceError, match="duplicate"):
        validate_memberships([member(deal, "MS08"), member(deal, "MS08")], [deal], DOMAINS)
    validate_memberships([member(deal, "MS08", "m1"), member(deal, "MS08", "m2")], [deal], DOMAINS)


def test_conflicting_manifestations_of_one_identity_fail_closed():
    with pytest.raises(FinancialIntelligenceError, match="conflicting manifestations"):
        unique_total([tx(), tx(amount="250.00")])
    assert unique_total([tx(), tx()])["counted"] == 1


# --- amounts, disclosure and valuation ---------------------------------------


def test_unknown_amount_stays_unknown_and_records_its_limitation():
    sealed = tx(amount=None, disclosure=Disclosure.CONFIDENTIAL)
    assert sealed.amount_decimal is None
    total = unique_total([sealed, tx(record="row-2", amount="40")])
    assert total["amount_decimal"] == "40"
    assert total["excluded_unknown_amount"] == 1
    assert unique_total([sealed])["amount_decimal"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        dict(amount=None, currency=None, valuation_basis=None, disclosure=Disclosure.DISCLOSED),
        dict(amount=None, currency="USD", valuation_basis=None, disclosure=Disclosure.UNKNOWN),
        dict(amount=100.0),
        dict(amount="-5"),
        dict(amount="NaN"),
        dict(valuation_basis=None),
        dict(valuation_basis="  "),
        dict(currency="usd"),
        dict(currency=None),
        dict(disclosure=Disclosure.CONFIDENTIAL),
        dict(source_sha256="ABC"),
        dict(source_record_id=""),
        dict(event_date="2024-13-01"),
        dict(event_date="1897-12-31"),
        dict(origin_ref=""),
    ],
)
def test_invalid_transactions_are_rejected(overrides):
    with pytest.raises(FinancialIntelligenceError):
        tx(**overrides)


def test_pre_1898_evidence_needs_a_justification():
    old = tx(
        event_date="1887-05-01",
        pre_baseline_justification="Establishes title continuity of the estate.",
    )
    assert old.event_date == "1887-05-01"
    assert tx(event_date="1898-01-01").event_date == "1898-01-01"


def test_mixed_currency_or_valuation_basis_cannot_be_summed():
    with pytest.raises(FinancialIntelligenceError, match="cannot be summed"):
        unique_total([tx(), tx(record="row-2", currency="EUR")])
    with pytest.raises(FinancialIntelligenceError, match="cannot be summed"):
        unique_total([tx(), tx(record="row-2", valuation_basis="book_value")])


# --- cross-source equivalence ------------------------------------------------


def test_only_certified_equivalence_merges_two_sources():
    a, b = tx(), tx(source="official:registry")
    lookalike = TransactionEquivalence(a.transaction_id, b.transaction_id, "same amount and date")
    assert unique_total([a, b], equivalences=[lookalike])["amount_decimal"] == "200.00"

    bound = TransactionEquivalence(a.transaction_id, b.transaction_id, "bridge-table", **PASS)
    merged = unique_total([a, b], equivalences=[bound])
    assert merged["amount_decimal"] == "100.00"
    assert merged["unique_transactions"] == 1
    assert len(set(canonical_ids([a, b], [bound]).values())) == 1


def test_equivalent_transactions_that_disagree_fail_closed():
    a, b = tx(), tx(source="official:registry", amount="90.00")
    bound = TransactionEquivalence(a.transaction_id, b.transaction_id, "bridge-table", **PASS)
    with pytest.raises(FinancialIntelligenceError, match="disagree"):
        unique_total([a, b], equivalences=[bound])
    with pytest.raises(FinancialIntelligenceError, match="unknown transaction"):
        canonical_ids([a], [bound])
    with pytest.raises(FinancialIntelligenceError):
        TransactionEquivalence(a.transaction_id, a.transaction_id, "m")


def test_equivalent_amounts_compare_numerically():
    a, b = tx(amount="100"), tx(source="official:registry", amount="100.00")
    bound = TransactionEquivalence(a.transaction_id, b.transaction_id, "bridge-table", **PASS)
    assert Decimal(unique_total([a, b], equivalences=[bound])["amount_decimal"]) == 100


# --- flow direction and character --------------------------------------------


@pytest.mark.parametrize(
    "origin,destination,expected",
    [
        ("US", "PR", FlowDirection.INBOUND),
        ("ES", "PR", FlowDirection.INBOUND),
        ("PR", "US", FlowDirection.OUTBOUND),
        ("PR", "PR", FlowDirection.INTERNAL),
        ("US", "ES", FlowDirection.NO_PR_NEXUS),
        (None, "PR", FlowDirection.UNRESOLVED),
        ("PR", None, FlowDirection.UNRESOLVED),
        ("", "PR", FlowDirection.UNRESOLVED),
    ],
)
def test_direction_comes_only_from_resolved_jurisdictions(origin, destination, expected):
    assert geographic_direction(origin, destination) is expected


def test_guarantees_and_asset_swaps_never_enter_a_cash_total():
    cash, guarantee, swap = tx(), tx(record="row-2", amount="900"), tx(record="row-3", amount="50")
    characters = [
        FlowCharacterAssertion(guarantee.transaction_id, FlowCharacter.CONTINGENT, "m1"),
        FlowCharacterAssertion(swap.transaction_id, FlowCharacter.NONCASH, "m1", **PASS),
    ]
    total = unique_total([cash, guarantee, swap], characters=characters)
    assert total["amount_decimal"] == "100.00"
    assert total["excluded_non_cash"] == 2


def test_retained_and_extracted_on_one_transaction_is_a_conflict():
    deal = tx()
    both = [
        FlowCharacterAssertion(deal.transaction_id, FlowCharacter.RETAINED, "m1", **PASS),
        FlowCharacterAssertion(deal.transaction_id, FlowCharacter.EXTRACTED, "m2", **PASS),
    ]
    assert character_conflicts(both) == frozenset({deal.transaction_id})
    assert character_conflicts(both[:1]) == frozenset()
    unproven = [both[0], FlowCharacterAssertion(deal.transaction_id, FlowCharacter.EXTRACTED, "m2")]
    assert character_conflicts(unproven) == frozenset()


# --- temporal ownership -------------------------------------------------------


def own(interval_id, subject, holder, share="1", kind=InterestKind.EQUITY, **overrides):
    fields = dict(
        interval_id=interval_id,
        subject_ref=subject,
        holder_ref=holder,
        kind=kind,
        source_manifestation_id="filing",
        share=share,
        **PASS,
    )
    fields.update(overrides)
    return OwnershipInterval(**fields)


def test_ultimate_holder_is_traced_through_intermediaries():
    chain = [
        own("i1", "operator", "holdco", "0.6"),
        own("i2", "holdco", "fund", "0.5"),
    ]
    (path,) = resolve_ultimate_holders(chain, "operator", "2024-06-30")
    assert path.holder_ref == "fund"
    assert path.interval_ids == ("i1", "i2")
    assert Decimal(path.effective_share) == Decimal("0.30")
    assert path.terminal is Terminal.NO_FURTHER_RECORD


def test_unknown_or_uncertified_link_ends_the_chain_unresolved():
    chain = [
        own("i1", "operator", "holdco", "0.6"),
        own("i2", "holdco", None, None, state=CertificationState.UNRESOLVED),
    ]
    (path,) = resolve_ultimate_holders(chain, "operator", "2024-06-30")
    assert path.holder_ref is None and path.effective_share is None
    assert path.terminal is Terminal.UNRESOLVED

    rumour = [
        own("i1", "operator", "holdco", evidence_basis=EvidenceBasis.HEURISTIC_DISCOVERY_ONLY)
    ]
    (path,) = resolve_ultimate_holders(rumour, "operator", "2024-06-30")
    assert path.holder_ref is None and path.terminal is Terminal.UNRESOLVED


def test_unknown_share_propagates_as_unknown_not_zero():
    chain = [own("i1", "operator", "holdco", None), own("i2", "holdco", "fund", "0.5")]
    (path,) = resolve_ultimate_holders(chain, "operator", "2024-06-30")
    assert path.holder_ref == "fund" and path.effective_share is None


def test_a_parent_is_not_a_beneficial_owner():
    chain = [own("i1", "operator", "holdco")]
    assert resolve_ultimate_holders(chain, "operator", "2024-06-30", InterestKind.BENEFICIAL) == ()
    assert holders_at(chain, "operator", "2024-06-30", InterestKind.CONTROL) == ()


def test_ownership_is_dated():
    history = [
        own("old", "plant", "utility", valid_from="1941-01-01", valid_to="2020-05-31"),
        own("new", "plant", "concession-spv", valid_from="2020-06-01"),
    ]
    assert [p.holder_ref for p in resolve_ultimate_holders(history, "plant", "2019-01-01")] == [
        "utility"
    ]
    assert [p.holder_ref for p in resolve_ultimate_holders(history, "plant", "2021-01-01")] == [
        "concession-spv"
    ]
    assert resolve_ultimate_holders(history, "plant", "1930-01-01") == ()


def test_ownership_gates():
    with pytest.raises(FinancialIntelligenceError, match="unknown holder"):
        own("i", "a", None, None)
    with pytest.raises(FinancialIntelligenceError, match="itself"):
        own("i", "a", "a")
    for share in ("0", "1.01", "-0.2", "abc"):
        with pytest.raises(FinancialIntelligenceError):
            own("i", "a", "b", share)
    with pytest.raises(FinancialIntelligenceError):
        own("i", "a", "b", valid_from="2020-01-02", valid_to="2020-01-01")
    with pytest.raises(FinancialIntelligenceError, match="predates"):
        own("i", "a", "b", valid_from="1850-01-01")
    with pytest.raises(FinancialIntelligenceError, match="circular"):
        resolve_ultimate_holders([own("i1", "a", "b"), own("i2", "b", "a")], "a", "2024-01-01")
    with pytest.raises(FinancialIntelligenceError, match="duplicate"):
        holders_at(
            [own("i1", "a", "b"), own("i1", "a", "c")], "a", "2024-01-01", InterestKind.EQUITY
        )


def test_certified_shares_cannot_exceed_the_whole():
    fine = [own("i1", "a", "b", "0.6"), own("i2", "a", "c", "0.4")]
    assert assert_share_conservation(fine, "a", "2024-01-01", InterestKind.EQUITY) == 1
    over = fine + [own("i3", "a", "d", "0.1")]
    with pytest.raises(FinancialIntelligenceError, match="exceed 100%"):
        assert_share_conservation(over, "a", "2024-01-01", InterestKind.EQUITY)
    unproven = fine + [own("i3", "a", "d", "0.1", state=CertificationState.UNRESOLVED)]
    assert assert_share_conservation(unproven, "a", "2024-01-01", InterestKind.EQUITY) == 1


# --- corporate continuity -----------------------------------------------------


def seen(observation_id, dimension, status, entity="utility", **overrides):
    fields = dict(
        observation_id=observation_id,
        entity_ref=entity,
        dimension=dimension,
        status=status,
        source_manifestation_id="docket",
        **PASS,
    )
    fields.update(overrides)
    return ContinuityObservation(**fields)


def test_operated_assets_do_not_prove_an_operating_company():
    observations = [
        seen("o1", "FINANCIAL", "BANKRUPT"),
        seen("o2", "ASSET_OWNERSHIP", "RETAINED"),
        seen("o3", "ASSET_OPERATION", "THIRD_PARTY_OPERATED"),
    ]
    profile = continuity_profile(observations, "utility", "2024-01-01")
    assert profile["FINANCIAL"].status == "BANKRUPT"
    assert profile["ASSET_OPERATION"].status == "THIRD_PARTY_OPERATED"
    assert profile["OPERATIONAL"].status == UNKNOWN
    assert profile["LEGAL"].status == UNKNOWN
    assert profile["REVENUE"].status == UNKNOWN
    assert set(profile) == {
        "LEGAL",
        "FINANCIAL",
        "OPERATIONAL",
        "ASSET_OWNERSHIP",
        "ASSET_OPERATION",
        "CORPORATE_CONTROL",
        "REVENUE",
    }


def test_conflicting_certified_statuses_are_kept_as_a_conflict():
    observations = [seen("o1", "LEGAL", "ACTIVE"), seen("o2", "LEGAL", "DISSOLVED")]
    status = continuity_profile(observations, "utility", "2024-01-01")["LEGAL"]
    assert status.status == CONFLICT
    assert status.supporting_observation_ids == ("o1", "o2")


def test_uncertified_status_is_a_candidate_only():
    observations = [seen("o1", "LEGAL", "DISSOLVED", state=CertificationState.PROVISIONAL)]
    status = continuity_profile(observations, "utility", "2024-01-01")["LEGAL"]
    assert status.status == UNKNOWN
    assert status.unpromoted_candidates == ("DISSOLVED",)


def test_continuity_is_dated_and_scoped_to_the_entity():
    observations = [
        seen("o1", "LEGAL", "ACTIVE", valid_to="2017-05-02"),
        seen("o2", "LEGAL", "SUSPENDED", valid_from="2017-05-03"),
        seen("o3", "LEGAL", "DISSOLVED", entity="another-company"),
    ]
    assert continuity_profile(observations, "utility", "2016-01-01")["LEGAL"].status == "ACTIVE"
    assert continuity_profile(observations, "utility", "2018-01-01")["LEGAL"].status == "SUSPENDED"


def test_continuity_gates():
    with pytest.raises(FinancialIntelligenceError, match="unknown continuity dimension"):
        seen("o", "REPUTATION", "ACTIVE")
    with pytest.raises(FinancialIntelligenceError, match="not a FINANCIAL status"):
        seen("o", "FINANCIAL", "DISSOLVED")
    with pytest.raises(FinancialIntelligenceError, match="duplicate"):
        continuity_profile(
            [seen("o", "LEGAL", "ACTIVE"), seen("o", "LEGAL", "ACTIVE")], "utility", "2024-01-01"
        )
