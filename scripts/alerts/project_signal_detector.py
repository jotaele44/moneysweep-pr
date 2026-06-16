"""Primary project-emergence detector for Contract-Sweeper."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .alert_deduper import build_dedupe_key, dedupe_events
from .alert_event_schema import AlertEvent, AlertLevel
from .alert_score_engine import score_record
from .project_watchlist import load_alert_thresholds, load_project_watchlist

_NONWORD = re.compile(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", re.UNICODE)


class ProjectSignalDetector:
    def __init__(
        self,
        watchlist: list[dict[str, Any]] | None = None,
        thresholds: dict[str, Any] | None = None,
    ):
        self.watchlist = watchlist if watchlist is not None else load_project_watchlist()
        self.thresholds = thresholds if thresholds is not None else load_alert_thresholds()

    def detect(self, records: Iterable[dict[str, Any]]) -> list[AlertEvent]:
        materialized = [dict(r) for r in records]
        source_counts = self._source_family_counts(materialized)
        vendor_counts = self._vendor_counts(materialized)
        events: list[AlertEvent] = []
        for record in materialized:
            for project in self.watchlist:
                if not self._matches_project(record, project):
                    continue
                project_id = str(project["project_id"])
                source = str(record.get("source_dataset") or record.get("source") or "")
                vendor = str(
                    record.get("recipient_name")
                    or record.get("vendor")
                    or record.get("vendor_name")
                    or ""
                )
                scored = score_record(
                    record,
                    project,
                    self.thresholds,
                    source_family_count=source_counts.get(project_id, 1),
                    vendor_recurrent=bool(vendor and vendor_counts.get(vendor.lower(), 0) > 1),
                )
                if scored.level == AlertLevel.BACKGROUND:
                    continue
                dedupe_key = build_dedupe_key(project_id, record)
                alert_id = self._alert_id(project_id, dedupe_key)
                events.append(
                    AlertEvent(
                        alert_id=alert_id,
                        project_id=project_id,
                        canonical_name=str(project.get("canonical_name", project_id)),
                        alert_level=scored.level,
                        score=scored.score,
                        trigger_reason=scored.reasons,
                        source=source,
                        source_family=source,
                        record_id=str(
                            record.get("record_id")
                            or record.get("award_id")
                            or record.get("id")
                            or ""
                        ),
                        record_date=str(
                            record.get("record_date")
                            or record.get("award_date")
                            or record.get("date")
                            or ""
                        ),
                        agency=str(
                            record.get("agency")
                            or record.get("awarding_agency")
                            or record.get("awarding_agency_name")
                            or ""
                        ),
                        vendor=vendor,
                        amount=_as_float(
                            record.get("obligated_amount")
                            or record.get("amount")
                            or record.get("award_amount")
                        ),
                        municipio=str(
                            record.get("municipio")
                            or record.get("pop_county")
                            or record.get("location")
                            or ""
                        ),
                        parcel_id=str(record.get("parcel_id") or record.get("facility") or ""),
                        project_stage=scored.stage,
                        confidence=scored.confidence,
                        requires_spiderweb=scored.requires_spiderweb,
                        dedupe_key=dedupe_key,
                        evidence={"source_record": record},
                    )
                )
        return dedupe_events(events)

    def _matches_project(self, record: dict[str, Any], project: dict[str, Any]) -> bool:
        text = _normalize(" ".join(str(value) for value in record.values()))
        names = [
            project.get("canonical_name", ""),
            *project.get("aliases", []),
            *project.get("entity_terms", []),
        ]
        return any(_normalize(str(name)) in text for name in names if str(name).strip())

    def _source_family_counts(self, records: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, set[str]] = {
            str(project["project_id"]): set() for project in self.watchlist
        }
        for record in records:
            source = str(record.get("source_dataset") or record.get("source") or "unknown")
            for project in self.watchlist:
                if self._matches_project(record, project):
                    counts[str(project["project_id"])].add(source)
        return {project_id: max(1, len(sources)) for project_id, sources in counts.items()}

    @staticmethod
    def _vendor_counts(records: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            vendor = str(
                record.get("recipient_name")
                or record.get("vendor")
                or record.get("vendor_name")
                or ""
            ).lower()
            if vendor:
                counts[vendor] = counts.get(vendor, 0) + 1
        return counts

    @staticmethod
    def _alert_id(project_id: str, dedupe_key: str) -> str:
        return f"ALERT-{project_id}-{hashlib.sha1(dedupe_key.encode()).hexdigest()[:10].upper()}"


def detect_project_signals(
    records: Iterable[dict[str, Any]], watchlist=None, thresholds=None
) -> list[AlertEvent]:
    return ProjectSignalDetector(watchlist=watchlist, thresholds=thresholds).detect(records)


def load_records_from_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_records_from_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))
    return records


def _normalize(value: str) -> str:
    return _NONWORD.sub(" ", value).lower().strip()


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None
