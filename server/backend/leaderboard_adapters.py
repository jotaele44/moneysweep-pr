"""Fail-closed financial leaderboard adapters.

Each adapter owns one financial measure and one identity contract.  The module
never aggregates by display name and never mixes currencies or non-equivalent
financial semantics.  Optional staging datasets are usable only when their
stable-ID requirements are satisfied; absence remains an explicit OPEN state.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical_v1"
PROCESSED = ROOT / "data" / "staging" / "processed"
ASG_EVIDENCE = ROOT / "data" / "manifests" / "asg_emergency_purchases"


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _manifest(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _money(value: object) -> float | None:
    """Parse a source-rendered currency amount without inferring currency."""
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    if cleaned in {"", "-", ".", "-."}:
        return None
    return _number(cleaned)


def _year(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def _competition_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(key=lambda row: (-row["metricValue"], row["entityId"]))
    prior_value: float | None = None
    rank = 0
    for position, row in enumerate(rows, start=1):
        if prior_value is None or row["metricValue"] != prior_value:
            rank = position
            prior_value = row["metricValue"]
        row["rank"] = rank
    return rows


def _entity_maps(data: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.Series], dict[str, set[str]], dict[str, str]]:
    entities = data["entities"]
    edges = data["edges"]
    municipalities = data["municipalities"]
    entity_rows = {str(row["entity_id"]): row for _, row in entities.iterrows()}
    locations: dict[str, set[str]] = defaultdict(set)
    located = edges[edges["edge_type"] == "LOCATED_IN"]
    for _, row in located.iterrows():
        source = str(row.get("source_node_id") or "")
        target = str(row.get("target_node_id") or "")
        if source and target:
            locations[source].add(target)
    muni_names = {
        str(row.get("name") or "").casefold(): str(row.get("municipality_id") or "")
        for _, row in municipalities.iterrows()
    }
    return entity_rows, locations, muni_names


def _accounting(total: int) -> dict[str, Any]:
    return {
        "inputRecords": int(total),
        "outOfScopeRecords": 0,
        "retainedRecords": 0,
        "excludedRecords": 0,
        "unresolvedRecords": 0,
    }


def _close(accounting: dict[str, Any]) -> None:
    in_scope = (
        accounting["retainedRecords"]
        + accounting["excludedRecords"]
        + accounting["unresolvedRecords"]
    )
    accounting["inScopeRecords"] = in_scope
    accounting["arithmeticClosed"] = (
        accounting["inputRecords"] == accounting["outOfScopeRecords"] + in_scope
    )


def _finalize(
    *,
    category_id: str,
    label: str,
    metric_type: str,
    rows: list[dict[str, Any]],
    accounting: dict[str, Any],
    limit: int | None,
    filters: dict[str, Any],
    manifests: list[dict[str, Any]],
    methodology: dict[str, Any],
    certification_state: str = "PROVISIONAL",
    reason: str | None = None,
) -> dict[str, Any]:
    _competition_ranks(rows)
    complete_rows = rows
    visible = complete_rows if limit is None else [row for row in complete_rows if row["rank"] <= limit]
    currencies = sorted({row["currency"] for row in complete_rows})
    _close(accounting)
    return {
        "categoryId": category_id,
        "categoryLabel": label,
        "metricType": metric_type,
        "certificationState": certification_state,
        "reason": reason,
        "rankingVersion": "moneysweep.leaderboard/v1.1",
        "computedAt": datetime.now(tz=UTC).isoformat(),
        "topN": limit,
        "tiesIncluded": True,
        "candidateCount": len(complete_rows),
        "currencies": currencies,
        "filters": filters,
        "accounting": accounting,
        "rows": visible,
        "sourceManifestations": manifests,
        "methodology": methodology,
    }


def _currency_guard(rows: list[dict[str, Any]], requested: str | None) -> None:
    currencies = sorted({row["currency"] for row in rows})
    if len(currencies) > 1 and requested is None:
        raise HTTPException(
            409,
            detail={
                "state": "UNRESOLVED",
                "reason": "multiple currencies present; choose one currency explicitly",
                "currencies": currencies,
            },
        )


def contract_awards(
    data: dict[str, pd.DataFrame],
    *,
    limit: int | None,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> dict[str, Any]:
    contracts = data["contracts"]
    entity_rows, locations, muni_names = _entity_maps(data)
    requested_muni = muni_names.get(municipality.casefold(), municipality) if municipality else None
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    accounting = _accounting(len(contracts))

    for _, row in contracts.iterrows():
        entity_id = str(row.get("contractor_entity_id") or "")
        entity = entity_rows.get(entity_id)
        year = _year(row.get("start_date"))
        if start_year is not None and (year is None or year < start_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if end_year is not None and (year is None or year > end_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if not entity_id or entity is None:
            accounting["unresolvedRecords"] += 1
            continue
        if entity_type and str(entity.get("entity_type") or "") != entity_type:
            accounting["outOfScopeRecords"] += 1
            continue
        if requested_muni:
            candidate_locations = locations.get(entity_id, set())
            if len(candidate_locations) > 1:
                accounting["unresolvedRecords"] += 1
                continue
            if len(candidate_locations) == 0 or requested_muni not in candidate_locations:
                accounting["outOfScopeRecords"] += 1
                continue
        amount = _number(row.get("award_amount"))
        if amount is None:
            accounting["excludedRecords"] += 1
            continue
        row_currency = str(row.get("currency") or "").strip().upper()
        if not row_currency:
            accounting["unresolvedRecords"] += 1
            continue
        if currency and row_currency != currency.upper():
            accounting["outOfScopeRecords"] += 1
            continue
        key = (entity_id, row_currency)
        agg = totals.setdefault(
            key,
            {
                "entityId": entity_id,
                "canonicalEntityId": entity_id,
                "entityDisplayName": str(entity.get("name") or entity_id),
                "entityType": str(entity.get("entity_type") or "") or None,
                "metricType": "AWARDED",
                "metricValue": 0.0,
                "currency": row_currency,
                "recordCount": 0,
                "sourceIds": set(),
                "evidenceIds": set(),
                "entityResolutionState": "CANONICAL_V1_ENTITY_ID",
                "financialValueState": "MEASURED_SOURCE_VALUE",
            },
        )
        agg["metricValue"] += amount
        agg["recordCount"] += 1
        if str(row.get("source_id") or ""):
            agg["sourceIds"].add(str(row.get("source_id")))
        if str(row.get("evidence_id") or ""):
            agg["evidenceIds"].add(str(row.get("evidence_id")))
        accounting["retainedRecords"] += 1

    rows: list[dict[str, Any]] = []
    for agg in totals.values():
        agg["sourceCount"] = len(agg.pop("sourceIds"))
        agg["evidenceCount"] = len(agg.pop("evidenceIds"))
        rows.append(agg)
    _currency_guard(rows, currency)
    result = _finalize(
        category_id="contract_award",
        label="Government contract awards",
        metric_type="AWARDED",
        rows=rows,
        accounting=accounting,
        limit=limit,
        filters={
            "startYear": start_year,
            "endYear": end_year,
            "municipality": municipality,
            "entityType": entity_type,
            "currency": currency,
        },
        manifests=[
            _manifest(CANON / "contracts.csv"),
            _manifest(CANON / "entities.csv"),
            _manifest(CANON / "edges.csv"),
            _manifest(CANON / "municipalities.csv"),
        ],
        methodology={
            "identity": "canonical_v1 contractor_entity_id only",
            "aggregation": "signed award_amount summed by entity and currency",
            "nulls": "missing award_amount excluded; blank currency unresolved",
            "geography": "LOCATED_IN candidate sets; multi-location identities unresolved",
        },
    )
    if not rows and accounting["excludedRecords"] > 0:
        result["certificationState"] = "OPEN"
        result["reason"] = (
            "Canonical contract identities are present, but all in-scope rows lack "
            "award_amount; no financial ranking can be certified from this source."
        )
    return result


def asg_emergency_source_native(
    _data: dict[str, pd.DataFrame],
    *,
    limit: int | None,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> dict[str, Any]:
    """Rank only ASG emergency-purchase rows carrying source-native Licitador IDs.

    The full source universe is still part of the accounting denominator. Rows
    lacking a source-native ID are explicit out-of-scope identity exclusions;
    they are never name-resolved or silently dropped.
    """
    subset_path = ASG_EVIDENCE / "source_native_rows_v1.csv"
    receipt_path = ASG_EVIDENCE / "materialization_receipt_20261005.json"

    if municipality or entity_type:
        raise HTTPException(
            422,
            "ASG supplier municipality/entity-type filters require an authoritative crosswalk",
        )
    if currency and currency.upper() != "USD":
        return _finalize(
            category_id="asg_emergency_purchase_source_native",
            label="ASG emergency purchase cost — source-native Licitador subset",
            metric_type="ASG_EMERGENCY_PURCHASE_COST",
            rows=[],
            accounting=_accounting(0),
            limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": currency},
            manifests=[],
            methodology={"currency": "ASG rendered purchase costs use the dollar-denominated Costo field"},
            certification_state="OPEN_NO_MATCHING_CURRENCY",
            reason="This bounded ASG emergency-purchase plane is denominated in USD.",
        )
    if not subset_path.exists() or not receipt_path.exists():
        return _finalize(
            category_id="asg_emergency_purchase_source_native",
            label="ASG emergency purchase cost — source-native Licitador subset",
            metric_type="ASG_EMERGENCY_PURCHASE_COST",
            rows=[],
            accounting=_accounting(0),
            limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": "USD"},
            manifests=[],
            methodology={"identity": "source-native asg_licitador_id required"},
            certification_state="OPEN_NOT_MATERIALIZED",
            reason="ASG source-native subset or authoritative materialization receipt is missing.",
        )

    subset_manifest = _manifest(subset_path)
    receipt_manifest = _manifest(receipt_path)
    # File mtimes are checkout-local metadata, not source identity. Keep ASG
    # snapshot manifestations byte/hash-stable across environments.
    subset_manifest.pop("modifiedAt", None)
    receipt_manifest.pop("modifiedAt", None)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        receipt = {}

    identity = receipt.get("identity") or {}
    financial = receipt.get("financialValue") or {}
    frozen = receipt.get("frozenArtifacts") or {}
    expected_subset = frozen.get("sourceNativeSubset") or {}
    readiness = receipt.get("readiness") or {}
    universe_total = int(receipt.get("authoritativeUniverseTotal") or 0)
    source_native_total = int(identity.get("sourceNativeRows") or 0)
    name_only_total = int(identity.get("nameOnlyRows") or 0)
    missing_vendor_total = int(identity.get("missingVendorRows") or 0)

    receipt_valid = all(
        [
            receipt.get("schemaVersion") == "moneysweep.asg-emergency-materialization-receipt/v1",
            receipt.get("state") == "SOURCE_MATERIALIZED",
            universe_total > 0,
            int(receipt.get("uniqueControlNumbers") or 0) == universe_total,
            receipt.get("duplicateControlNumbers") == 0,
            receipt.get("missingControlNumbers") == 0,
            source_native_total + name_only_total + missing_vendor_total == universe_total,
            identity.get("arithmeticClosed") is True,
            financial.get("invalidAmountRows") == 0,
            financial.get("sourceNativeInvalidAmountRows") == 0,
            int(identity.get("distinctSourceNativeIds") or 0)
            == int(financial.get("boundedEligibleEntityCount") or -1),
            (identity.get("supplierRegistryCrossCheck") or {}).get("allCandidateIdsMatched")
            is True,
            readiness.get("boundedSourceNativeLeaderboardReady") is True,
            readiness.get("wholeSourceLeaderboardReady") is False,
            str(expected_subset.get("sha256") or "") == subset_manifest["sha256"],
        ]
    )
    frame = _read(subset_path)
    if int(expected_subset.get("rows") or -1) != len(frame):
        receipt_valid = False
    if len(frame) != source_native_total:
        receipt_valid = False

    subset_integrity_rows = 0
    subset_integrity_entities: set[str] = set()
    subset_integrity_amount = 0.0
    if receipt_valid:
        for _, row in frame.iterrows():
            registration_id = str(row.get("vendor_registration_id") or "").strip()
            scheme = str(row.get("vendor_identity_scheme") or "").strip()
            state = str(row.get("vendor_identity_state") or "").strip()
            amount = _money(row.get("obligation_amount"))
            if (
                not registration_id
                or scheme != "asg_licitador_id"
                or state != "SOURCE_NATIVE_ASG_LICITADOR_ID"
                or amount is None
            ):
                receipt_valid = False
                break
            subset_integrity_rows += 1
            subset_integrity_entities.add(registration_id)
            subset_integrity_amount += amount

        if (
            subset_integrity_rows != int(financial.get("boundedEligibleRows") or -1)
            or len(subset_integrity_entities)
            != int(financial.get("boundedEligibleEntityCount") or -1)
            or round(subset_integrity_amount, 2)
            != round(float(financial.get("boundedEligibleAmountTotal") or -1), 2)
        ):
            receipt_valid = False

    if not receipt_valid:
        return _finalize(
            category_id="asg_emergency_purchase_source_native",
            label="ASG emergency purchase cost — source-native Licitador subset",
            metric_type="ASG_EMERGENCY_PURCHASE_COST",
            rows=[],
            accounting=_accounting(universe_total),
            limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": "USD"},
            manifests=[subset_manifest, receipt_manifest],
            methodology={"identity": "source-native asg_licitador_id required"},
            certification_state="OPEN_INVALID_SOURCE_RECEIPT",
            reason="ASG full-source receipt or source-native subset binding failed validation.",
        )

    accounting = _accounting(universe_total)
    accounting["outOfScopeRecords"] = name_only_total + missing_vendor_total
    totals: dict[str, dict[str, Any]] = {}

    for _, row in frame.iterrows():
        year = _year(row.get("fiscal_year"))
        if start_year is not None and (year is None or year < start_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if end_year is not None and (year is None or year > end_year):
            accounting["outOfScopeRecords"] += 1
            continue

        registration_id = str(row.get("vendor_registration_id") or "").strip()
        scheme = str(row.get("vendor_identity_scheme") or "").strip()
        state = str(row.get("vendor_identity_state") or "").strip()
        if (
            not registration_id
            or scheme != "asg_licitador_id"
            or state != "SOURCE_NATIVE_ASG_LICITADOR_ID"
        ):
            accounting["unresolvedRecords"] += 1
            continue

        amount = _money(row.get("obligation_amount"))
        if amount is None:
            accounting["excludedRecords"] += 1
            continue

        entity_id = f"asg_licitador_id:{registration_id}"
        agg = totals.setdefault(
            registration_id,
            {
                "entityId": entity_id,
                "canonicalEntityId": None,
                "entityDisplayName": "",
                "entityType": "asg_supplier",
                "metricType": "ASG_EMERGENCY_PURCHASE_COST",
                "metricValue": 0.0,
                "currency": "USD",
                "recordCount": 0,
                "sourceDisplayNames": set(),
                "controlNumbers": set(),
                "entityResolutionState": "SOURCE_NATIVE_ASG_LICITADOR_ID",
                "financialValueState": "MEASURED_ASG_EMERGENCY_PURCHASE_COST",
            },
        )
        display = str(row.get("vendor_name") or "").strip()
        if display:
            agg["sourceDisplayNames"].add(display)
        control = str(row.get("control_number") or "").strip()
        if control:
            agg["controlNumbers"].add(control)
        agg["metricValue"] += amount
        agg["recordCount"] += 1
        accounting["retainedRecords"] += 1

    rows: list[dict[str, Any]] = []
    for agg in totals.values():
        names = sorted(agg.pop("sourceDisplayNames"), key=lambda value: (value.casefold(), value))
        agg["entityDisplayName"] = names[0] if names else agg["entityId"]
        agg["sourceDisplayNames"] = names
        agg["controlNumbers"] = sorted(agg["controlNumbers"])
        agg["metricValue"] = round(float(agg["metricValue"]), 2)
        rows.append(agg)

    canonical_source = frozen.get("canonicalParsedCorpus") or {}
    raw_bundle = frozen.get("rawAndParsedBundle") or {}
    if (
        int(canonical_source.get("rows") or 0) != universe_total
        or not str(canonical_source.get("sha256") or "")
        or not str(raw_bundle.get("storagePath") or "")
        or not str(raw_bundle.get("sha256") or "")
    ):
        return _finalize(
            category_id="asg_emergency_purchase_source_native",
            label="ASG emergency purchase cost — source-native Licitador subset",
            metric_type="ASG_EMERGENCY_PURCHASE_COST",
            rows=[],
            accounting=_accounting(universe_total),
            limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": "USD"},
            manifests=[subset_manifest, receipt_manifest],
            methodology={"identity": "source-native asg_licitador_id required"},
            certification_state="OPEN_INVALID_SOURCE_RECEIPT",
            reason="ASG October 5 corpus or acquisition-bundle binding is incomplete.",
        )

    source_manifestations = [
        subset_manifest,
        receipt_manifest,
        {
            "path": str(raw_bundle.get("storagePath") or ""),
            "bytes": int(raw_bundle.get("bytes") or 0),
            "sha256": str(raw_bundle.get("sha256") or ""),
            "manifestationType": "FLOOT_OBJECT_STORAGE_RAW_AND_PARSED_BUNDLE",
        },
    ]
    result = _finalize(
        category_id="asg_emergency_purchase_source_native",
        label="ASG emergency purchase cost — source-native Licitador subset",
        metric_type="ASG_EMERGENCY_PURCHASE_COST",
        rows=rows,
        accounting=accounting,
        limit=limit,
        filters={"startYear": start_year, "endYear": end_year, "currency": "USD"},
        manifests=source_manifestations,
        methodology={
            "identity": "explicit source-native ASG Licitador ID only; names are display-only",
            "aggregation": "ASG emergency-purchase Costo summed by asg_licitador_id",
            "fullSourceUniverse": universe_total,
            "eligibleSourceNativeRows": source_native_total,
            "excludedNameOnlyRows": name_only_total,
            "excludedMissingVendorRows": missing_vendor_total,
            "scopeBoundary": "does not claim all ASG emergency purchases or total ASG emergency spending",
            "completenessOrdering": "numerocontrol",
            "currency": "USD",
        },
        certification_state="PROVISIONAL_BOUNDED_SOURCE_NATIVE",
        reason=(
            "Full ASG source coverage is closed, but this ranking is explicitly limited "
            "to rows carrying a source-native ASG Licitador ID."
        ),
    )
    result["sourceVersion"] = {
        "type": "LIVE_PORTAL_MATERIALIZATION",
        "sourceId": "asg_emergency_purchases",
        "capturedAt": str(receipt.get("observedAt") or ""),
        "ordering": "numerocontrol",
        "authoritativeUniverseTotal": universe_total,
        "sourceSha256": str(canonical_source.get("sha256") or ""),
        "rawBundleSha256": str(raw_bundle.get("sha256") or ""),
        "economicActivityInference": False,
    }
    return result


def debt_issuance(
    data: dict[str, pd.DataFrame],
    *,
    limit: int | None,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> dict[str, Any]:
    path = CANON / "debt_instruments.csv"
    frame = _read(path)
    entity_rows, locations, muni_names = _entity_maps(data)
    requested_muni = muni_names.get(municipality.casefold(), municipality) if municipality else None
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    accounting = _accounting(len(frame))

    for _, row in frame.iterrows():
        entity_id = str(row.get("issuer_entity_id") or "")
        entity = entity_rows.get(entity_id)
        year = _year(row.get("issue_year"))
        if start_year is not None and (year is None or year < start_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if end_year is not None and (year is None or year > end_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if not entity_id or entity is None:
            accounting["unresolvedRecords"] += 1
            continue
        if entity_type and str(entity.get("entity_type") or "") != entity_type:
            accounting["outOfScopeRecords"] += 1
            continue
        if requested_muni:
            candidate_locations = locations.get(entity_id, set())
            if len(candidate_locations) > 1:
                accounting["unresolvedRecords"] += 1
                continue
            if len(candidate_locations) == 0 or requested_muni not in candidate_locations:
                accounting["outOfScopeRecords"] += 1
                continue
        amount = _number(row.get("par_amount"))
        if amount is None:
            accounting["excludedRecords"] += 1
            continue
        row_currency = str(row.get("currency") or "").strip().upper()
        if not row_currency:
            accounting["unresolvedRecords"] += 1
            continue
        if currency and row_currency != currency.upper():
            accounting["outOfScopeRecords"] += 1
            continue
        key = (entity_id, row_currency)
        agg = totals.setdefault(
            key,
            {
                "entityId": entity_id,
                "canonicalEntityId": entity_id,
                "entityDisplayName": str(entity.get("name") or entity_id),
                "entityType": str(entity.get("entity_type") or "") or None,
                "metricType": "DEBT_ISSUED_PAR",
                "metricValue": 0.0,
                "currency": row_currency,
                "recordCount": 0,
                "debtClasses": set(),
                "evidenceIds": set(),
                "entityResolutionState": "CANONICAL_V1_ENTITY_ID",
                "financialValueState": "MEASURED_PAR_AMOUNT",
            },
        )
        agg["metricValue"] += amount
        agg["recordCount"] += 1
        if str(row.get("debt_class") or ""):
            agg["debtClasses"].add(str(row.get("debt_class")))
        if str(row.get("evidence_id") or ""):
            agg["evidenceIds"].add(str(row.get("evidence_id")))
        accounting["retainedRecords"] += 1

    rows = []
    for agg in totals.values():
        agg["debtClasses"] = sorted(agg["debtClasses"])
        agg["evidenceCount"] = len(agg.pop("evidenceIds"))
        rows.append(agg)
    _currency_guard(rows, currency)
    return _finalize(
        category_id="debt_issuance",
        label="Public debt issued (par amount)",
        metric_type="DEBT_ISSUED_PAR",
        rows=rows,
        accounting=accounting,
        limit=limit,
        filters={
            "startYear": start_year,
            "endYear": end_year,
            "municipality": municipality,
            "entityType": entity_type,
            "currency": currency,
        },
        manifests=[_manifest(path), _manifest(CANON / "entities.csv")],
        methodology={
            "identity": "canonical_v1 issuer_entity_id only",
            "aggregation": "par_amount summed by issuer and currency",
            "nonEquivalence": "par amount is issuance face value, not outstanding debt, debt service, expenditure, or cash received",
            "nulls": "missing par_amount excluded; blank currency unresolved",
        },
    )


def _federal_awards(
    _data: dict[str, pd.DataFrame],
    *,
    category_id: str,
    label: str,
    category_filter: Callable[[str, str], bool],
    limit: int | None,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> dict[str, Any]:
    path = PROCESSED / "pr_all_awards_master.csv"
    if municipality or entity_type:
        raise HTTPException(
            422,
            "municipality/entity_type filters are unavailable for source-native UEI rankings until an authoritative crosswalk is mounted",
        )
    if currency and currency.upper() != "USD":
        return _finalize(
            category_id=category_id,
            label=label,
            metric_type="OBLIGATED",
            rows=[],
            accounting=_accounting(0),
            limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": currency},
            manifests=[],
            methodology={"identity": "recipient_uei", "currency": "MoneySweep federal-award master monetary fields are USD"},
            certification_state="OPEN_NO_MATCHING_CURRENCY",
            reason="The standardized federal-award master is denominated in USD.",
        )
    if not path.exists():
        return _finalize(
            category_id=category_id,
            label=label,
            metric_type="OBLIGATED",
            rows=[],
            accounting=_accounting(0),
            limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": currency or "USD"},
            manifests=[],
            methodology={"identity": "recipient_uei required; names are display-only"},
            certification_state="OPEN_NOT_MATERIALIZED",
            reason="data/staging/processed/pr_all_awards_master.csv is not mounted in this checkout",
        )
    frame = _read(path)
    accounting = _accounting(len(frame))
    totals: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        source_dataset = str(row.get("source_dataset") or "").strip().lower()
        award_category = str(row.get("award_category") or "").strip().lower()
        if not category_filter(source_dataset, award_category):
            accounting["outOfScopeRecords"] += 1
            continue
        year = _year(row.get("fiscal_year") or row.get("award_date"))
        if start_year is not None and (year is None or year < start_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if end_year is not None and (year is None or year > end_year):
            accounting["outOfScopeRecords"] += 1
            continue
        uei = str(row.get("recipient_uei") or "").strip().upper()
        if not uei:
            accounting["unresolvedRecords"] += 1
            continue
        amount = _number(row.get("obligated_amount"))
        if amount is None:
            accounting["excludedRecords"] += 1
            continue
        agg = totals.setdefault(
            uei,
            {
                "entityId": f"uei:{uei}",
                "canonicalEntityId": None,
                "entityDisplayName": str(row.get("recipient_name") or uei),
                "entityType": "federal_award_recipient",
                "metricType": "OBLIGATED",
                "metricValue": 0.0,
                "currency": "USD",
                "recordCount": 0,
                "sourceDatasets": set(),
                "entityResolutionState": "SOURCE_NATIVE_UEI",
                "financialValueState": "STANDARDIZED_OBLIGATED_AMOUNT",
            },
        )
        agg["metricValue"] += amount
        agg["recordCount"] += 1
        if source_dataset:
            agg["sourceDatasets"].add(source_dataset)
        accounting["retainedRecords"] += 1
    rows = []
    for agg in totals.values():
        agg["sourceDatasets"] = sorted(agg["sourceDatasets"])
        rows.append(agg)
    return _finalize(
        category_id=category_id,
        label=label,
        metric_type="OBLIGATED",
        rows=rows,
        accounting=accounting,
        limit=limit,
        filters={"startYear": start_year, "endYear": end_year, "currency": "USD"},
        manifests=[_manifest(path)],
        methodology={
            "identity": "source-native recipient_uei only; recipient_name is display-only",
            "aggregation": "standardized obligated_amount summed by UEI",
            "currency": "MoneySweep unified federal-award master obligation measure is USD",
            "classification": "award_category/source_dataset filter; no cross-measure aggregation",
        },
    )


def federal_contract_obligations(data: dict[str, pd.DataFrame], **kwargs) -> dict[str, Any]:
    return _federal_awards(
        data,
        category_id="federal_obligation",
        label="Federal contract obligations",
        category_filter=lambda source, category: category in {"contract", "contracts"} or source == "contracts",
        **kwargs,
    )


def federal_grants(data: dict[str, pd.DataFrame], **kwargs) -> dict[str, Any]:
    return _federal_awards(
        data,
        category_id="federal_grant",
        label="Federal grant obligations",
        category_filter=lambda source, category: category in {"grant", "grants"} or source == "grants",
        **kwargs,
    )


def federal_assistance(data: dict[str, pd.DataFrame], **kwargs) -> dict[str, Any]:
    assistance_sources = {
        "grants",
        "fema_pa",
        "fema_hmgp",
        "research",
        "slfrf",
        "cdbg_dr",
        "dot",
        "usda",
        "doe",
        "hud",
        "sbir",
    }
    return _federal_awards(
        data,
        category_id="federal_assistance",
        label="Federal assistance obligations",
        category_filter=lambda source, category: source in assistance_sources or category in {"grant", "grants", "assistance"},
        **kwargs,
    )


def disaster_assistance(data: dict[str, pd.DataFrame], **kwargs) -> dict[str, Any]:
    disaster_sources = {"fema_pa", "fema_hmgp", "cdbg_dr"}
    return _federal_awards(
        data,
        category_id="disaster_assistance",
        label="Disaster-recovery assistance obligations",
        category_filter=lambda source, _category: source in disaster_sources,
        **kwargs,
    )


def campaign_contributions_received(
    _data: dict[str, pd.DataFrame],
    *,
    limit: int | None,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> dict[str, Any]:
    if municipality or entity_type:
        raise HTTPException(422, "campaign committee geography/entity-type filters require an authoritative crosswalk")
    if currency and currency.upper() != "USD":
        return _finalize(
            category_id="campaign_contribution_received",
            label="Campaign contributions received by authoritative FEC committee",
            metric_type="CONTRIBUTIONS_RECEIVED",
            rows=[], accounting=_accounting(0), limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": currency},
            manifests=[], methodology={"currency": "FEC monetary receipts are USD"},
            certification_state="OPEN_NO_MATCHING_CURRENCY",
            reason="The FEC receipt plane is denominated in USD.",
        )
    edges_path = PROCESSED / "pr_campaign_finance_edges.csv"
    committees_path = PROCESSED / "pr_campaign_finance_committees.csv"
    if not edges_path.exists() or not committees_path.exists():
        return _finalize(
            category_id="campaign_contribution_received",
            label="Campaign contributions received by authoritative FEC committee",
            metric_type="CONTRIBUTIONS_RECEIVED",
            rows=[], accounting=_accounting(0), limit=limit,
            filters={"startYear": start_year, "endYear": end_year, "currency": "USD"},
            manifests=[], methodology={"identity": "authoritative FEC committee ID required"},
            certification_state="OPEN_NOT_MATERIALIZED",
            reason="campaign-finance graph/committee materialization is not mounted in this checkout",
        )
    edges = _read(edges_path)
    committees = _read(committees_path)
    authoritative: dict[str, pd.Series] = {}
    for _, row in committees.iterrows():
        fec_id = str(row.get("fec_committee_id") or "").strip()
        entity_id = str(row.get("committee_entity_id") or "").strip()
        if fec_id and entity_id and entity_id == fec_id:
            authoritative[entity_id] = row
    accounting = _accounting(len(edges))
    totals: dict[str, dict[str, Any]] = {}
    for _, row in edges.iterrows():
        if str(row.get("edge_type") or "") != "CONTRIBUTED_TO":
            accounting["outOfScopeRecords"] += 1
            continue
        target = str(row.get("target_entity_id") or "").strip()
        committee = authoritative.get(target)
        if committee is None:
            accounting["unresolvedRecords"] += 1
            continue
        year = _year(row.get("transaction_date") or row.get("cycle"))
        if start_year is not None and (year is None or year < start_year):
            accounting["outOfScopeRecords"] += 1
            continue
        if end_year is not None and (year is None or year > end_year):
            accounting["outOfScopeRecords"] += 1
            continue
        amount = _number(row.get("amount"))
        if amount is None:
            accounting["excludedRecords"] += 1
            continue
        agg = totals.setdefault(
            target,
            {
                "entityId": f"fec_committee:{target}",
                "canonicalEntityId": None,
                "entityDisplayName": str(committee.get("canonical_name") or target),
                "entityType": "campaign_committee",
                "metricType": "CONTRIBUTIONS_RECEIVED",
                "metricValue": 0.0,
                "currency": "USD",
                "recordCount": 0,
                "sourceDatasets": set(),
                "entityResolutionState": "AUTHORITATIVE_FEC_COMMITTEE_ID",
                "financialValueState": "MEASURED_CONTRIBUTION_RECEIPT",
            },
        )
        agg["metricValue"] += amount
        agg["recordCount"] += 1
        source = str(row.get("source_dataset") or "")
        if source:
            agg["sourceDatasets"].add(source)
        accounting["retainedRecords"] += 1
    rows = []
    for agg in totals.values():
        agg["sourceDatasets"] = sorted(agg["sourceDatasets"])
        rows.append(agg)
    return _finalize(
        category_id="campaign_contribution_received",
        label="Campaign contributions received by authoritative FEC committee",
        metric_type="CONTRIBUTIONS_RECEIVED",
        rows=rows, accounting=accounting, limit=limit,
        filters={"startYear": start_year, "endYear": end_year, "currency": "USD"},
        manifests=[_manifest(edges_path), _manifest(committees_path)],
        methodology={
            "identity": "target committee must carry a nonblank authoritative fec_committee_id; normalized-name-only committee identities are unresolved",
            "aggregation": "CONTRIBUTED_TO edge amounts summed by FEC committee ID",
            "donorBoundary": "donor stable IDs synthesized from names are not promoted to donor identity and are never used for donor rankings",
        },
    )


Adapter = Callable[..., dict[str, Any]]

ADAPTERS: dict[str, Adapter] = {
    "canonical_contracts": contract_awards,
    "canonical_debt": debt_issuance,
    "asg_emergency_source_native": asg_emergency_source_native,
    "federal_awards_contracts": federal_contract_obligations,
    "federal_awards_grants": federal_grants,
    "federal_awards_assistance": federal_assistance,
    "federal_awards_disaster": disaster_assistance,
    "campaign_finance_receipts": campaign_contributions_received,
}


def run_adapter(
    adapter_id: str,
    data: dict[str, pd.DataFrame],
    *,
    limit: int | None,
    start_year: int | None,
    end_year: int | None,
    municipality: str | None,
    entity_type: str | None,
    currency: str | None,
) -> dict[str, Any]:
    adapter = ADAPTERS.get(adapter_id)
    if adapter is None:
        raise HTTPException(500, f"ontology references unknown leaderboard adapter: {adapter_id}")
    return adapter(
        data,
        limit=limit,
        start_year=start_year,
        end_year=end_year,
        municipality=municipality,
        entity_type=entity_type,
        currency=currency,
    )
