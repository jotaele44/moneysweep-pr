"""Offline Tranche B staging controller for dropped tabular source files."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT
from scripts.source_intake_helpers import (
    ensure_required_columns,
    load_tabular_dropzone,
    map_frame,
    normalize_name,
    write_canonical_csv,
)

LOCAL_CONTRACT_COLUMNS = [
    "source_id",
    "source_file",
    "record_id",
    "contract_id",
    "contract_title",
    "contractor_name",
    "agency_name",
    "amount",
    "start_date",
    "end_date",
    "fiscal_year",
    "municipality",
    "procurement_type",
    "status",
    "raw_text_excerpt",
    "evidence_tier",
    "confidence",
]
INFRASTRUCTURE_PROJECT_COLUMNS = [
    "source_id",
    "source_file",
    "project_id",
    "project_name",
    "asset_type",
    "owner_agency",
    "municipality",
    "status",
    "amount",
    "funding_program",
    "start_date",
    "completion_date",
    "latitude",
    "longitude",
    "raw_text_excerpt",
    "evidence_tier",
    "confidence",
]
INFRASTRUCTURE_FACT_COLUMNS = [
    "source_id",
    "source_file",
    "fact_id",
    "asset_name",
    "asset_type",
    "owner_agency",
    "fiscal_year",
    "metric_name",
    "metric_value",
    "unit",
    "municipality",
    "raw_text_excerpt",
    "evidence_tier",
    "confidence",
]
LOBBYING_COLUMNS = [
    "source_id",
    "source_file",
    "record_id",
    "registrant_name",
    "client_name",
    "person_name",
    "entity_name",
    "relationship_type",
    "registration_date",
    "termination_date",
    "jurisdiction",
    "raw_text_excerpt",
    "evidence_tier",
    "confidence",
]
CONTRACTOR_REFERENCE_COLUMNS = [
    "source_id",
    "source_file",
    "contractor_name",
    "normalized_name",
    "uei",
    "cage",
    "duns",
    "agency_reference",
    "fiscal_year",
    "listing_type",
    "raw_text_excerpt",
    "evidence_tier",
    "confidence",
]

LOCAL_CONTRACT_MAP = {
    "record_id": ["record_id", "id", "ID", "Número", "Numero", "Row ID"],
    "contract_id": ["contract_id", "Contract ID", "Contrato", "Contract Number"],
    "contract_title": [
        "contract_title",
        "Title",
        "Titulo",
        "Descripción",
        "Description",
    ],
    "contractor_name": ["contractor_name", "Contratista", "Contractor", "Vendor Name"],
    "agency_name": ["agency_name", "Agencia", "Agency", "Entidad", "Department"],
    "amount": ["amount", "Monto", "Amount", "Contract Value", "Total"],
    "start_date": ["start_date", "Fecha Inicio", "Start Date"],
    "end_date": ["end_date", "Fecha Fin", "End Date"],
    "fiscal_year": ["fiscal_year", "FY", "Año Fiscal", "Fiscal Year"],
    "municipality": ["municipality", "Municipio", "Municipality", "Ciudad"],
    "procurement_type": ["procurement_type", "Tipo", "Type", "Award Type"],
    "status": ["status", "Estado", "Estatus", "Status"],
}
PROJECT_MAP = {
    "project_id": ["project_id", "Project ID", "Número de Proyecto", "ID"],
    "project_name": ["project_name", "Project Name", "Proyecto", "Nombre del Proyecto"],
    "asset_type": ["asset_type", "Asset Type", "Tipo de Activo", "Category"],
    "owner_agency": ["owner_agency", "Owner", "Agencia", "Agency"],
    "municipality": ["municipality", "Municipio", "Municipality"],
    "status": ["status", "Estado", "Status"],
    "amount": ["amount", "Monto", "Amount", "Budget", "Cost"],
    "funding_program": ["funding_program", "Funding Program", "Programa", "Fund"],
    "start_date": ["start_date", "Start Date", "Fecha Inicio"],
    "completion_date": ["completion_date", "Completion Date", "Fecha Terminación"],
    "latitude": ["latitude", "Lat", "Latitude"],
    "longitude": ["longitude", "Lon", "Longitude"],
}
FACT_MAP = {
    "fact_id": ["fact_id", "ID", "Record ID"],
    "asset_name": ["asset_name", "Asset", "Facility", "Sistema", "Project"],
    "asset_type": ["asset_type", "Asset Type", "Tipo"],
    "owner_agency": ["owner_agency", "Owner", "Agency", "Agencia"],
    "fiscal_year": ["fiscal_year", "FY", "Fiscal Year", "Año Fiscal"],
    "metric_name": ["metric_name", "Metric", "Indicador", "Measure"],
    "metric_value": ["metric_value", "Value", "Valor", "Amount"],
    "unit": ["unit", "Unit", "Unidad"],
    "municipality": ["municipality", "Municipio", "Municipality"],
}
LOBBYING_MAP = {
    "record_id": ["record_id", "ID", "filing_uuid", "Registration Number"],
    "registrant_name": ["registrant_name", "Registrant", "Cabildero", "Lobbyist Name"],
    "client_name": ["client_name", "Client", "Cliente"],
    "person_name": ["person_name", "Person", "Lobbyist", "Nombre Cabildero"],
    "entity_name": ["entity_name", "Entity", "Entidad", "Organization"],
    "relationship_type": ["relationship_type", "Relationship", "Type", "filing_type"],
    "registration_date": [
        "registration_date",
        "Registration Date",
        "Fecha de Registro",
    ],
    "termination_date": ["termination_date", "Termination Date", "Expiry Date"],
    "jurisdiction": ["jurisdiction", "Jurisdiction", "client_state", "State"],
}
CONTRACTOR_REF_MAP = {
    "contractor_name": [
        "contractor_name",
        "Contractor",
        "Vendor Name",
        "Name",
        "Nombre",
    ],
    "normalized_name": ["normalized_name", "entity_normalized", "Normalized Name"],
    "uei": ["uei", "UEI", "Unique Entity ID"],
    "cage": ["cage", "CAGE", "CAGE Code"],
    "duns": ["duns", "DUNS", "Duns Number"],
    "agency_reference": [
        "agency_reference",
        "Agency",
        "Source Agency",
        "Listing Agency",
    ],
    "fiscal_year": ["fiscal_year", "FY", "Fiscal Year"],
    "listing_type": ["listing_type", "Listing Type", "Type", "Status"],
}


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    dropzone: str
    output: str
    schema: str
    columns: list[str]
    column_map: dict[str, list[str]]
    dedupe_columns: tuple[str, ...]


SOURCE_SPECS = {
    "act": SourceSpec(
        "act_transition_contracts",
        "data/raw/ACT Transition Contracts",
        "data/staging/processed/pr_act_transition_contracts.csv",
        "schemas/local_contracts.schema.json",
        LOCAL_CONTRACT_COLUMNS,
        LOCAL_CONTRACT_MAP,
        ("contract_id", "contractor_name"),
    ),
    "acuden": SourceSpec(
        "acuden_2024_transition",
        "data/raw/ACUDEN Transition Contracts",
        "data/staging/processed/pr_acuden_transition.csv",
        "schemas/local_contracts.schema.json",
        LOCAL_CONTRACT_COLUMNS,
        LOCAL_CONTRACT_MAP,
        ("contract_id", "contractor_name"),
    ),
    "prasa_projects": SourceSpec(
        "prasa_completed_projects",
        "data/raw/PRASA Completed Projects",
        "data/staging/processed/prasa_completed_projects.csv",
        "schemas/infrastructure_projects.schema.json",
        INFRASTRUCTURE_PROJECT_COLUMNS,
        PROJECT_MAP,
        ("project_id", "project_name"),
    ),
    "prasa_cer": SourceSpec(
        "prasa_fy2024_cer",
        "data/raw/PRASA CER",
        "data/staging/processed/prasa_cer_facts.csv",
        "schemas/infrastructure_fiscal_facts.schema.json",
        INFRASTRUCTURE_FACT_COLUMNS,
        FACT_MAP,
        ("fact_id", "metric_name"),
    ),
    "cabilderos": SourceSpec(
        "pr_cabilderos",
        "data/raw/Cabilderos",
        "data/staging/processed/pr_cabilderos_registry.csv",
        "schemas/lobbying_registry.schema.json",
        LOBBYING_COLUMNS,
        LOBBYING_MAP,
        ("registrant_name", "client_name", "registration_date"),
    ),
    "lda": SourceSpec(
        "federal_lda_registrants",
        "data/raw/Federal LDA Registrants",
        "data/staging/processed/federal_lda_registrants.csv",
        "schemas/lobbying_registry.schema.json",
        LOBBYING_COLUMNS,
        LOBBYING_MAP,
        ("record_id", "registrant_name", "client_name"),
    ),
    "dcaa": SourceSpec(
        "dcaa_active_contractors",
        "data/raw/DCAA Active Contractors",
        "data/staging/processed/dcaa_active_contractors.csv",
        "schemas/contractor_reference.schema.json",
        CONTRACTOR_REFERENCE_COLUMNS,
        CONTRACTOR_REF_MAP,
        ("contractor_name", "uei", "cage"),
    ),
}


def _stable_record_ids(frame: pd.DataFrame, prefix: str, id_col: str) -> None:
    if id_col not in frame.columns:
        return
    missing = frame[id_col].astype(str).str.strip() == ""
    frame.loc[missing, id_col] = [f"{prefix}-{i + 1:06d}" for i in range(int(missing.sum()))]


def _postprocess(spec: SourceSpec, frame: pd.DataFrame) -> pd.DataFrame:
    if "contractor_name" in frame.columns and "normalized_name" in frame.columns:
        missing = frame["normalized_name"].astype(str).str.strip() == ""
        frame.loc[missing, "normalized_name"] = frame.loc[missing, "contractor_name"].map(
            normalize_name
        )

    for id_col in ("record_id", "project_id", "fact_id"):
        if id_col in frame.columns:
            _stable_record_ids(frame, spec.source_id, id_col)

    if "jurisdiction" in frame.columns:
        blank = frame["jurisdiction"].astype(str).str.strip() == ""
        frame.loc[blank, "jurisdiction"] = "PR" if spec.source_id.startswith("pr_") else "US"

    provenance_columns = {
        "source_id",
        "source_file",
        "raw_text_excerpt",
        "evidence_tier",
        "confidence",
    }
    non_provenance = [col for col in frame.columns if col not in provenance_columns]
    if non_provenance and not frame.empty:
        joined = frame[non_provenance].astype(str).agg("".join, axis=1)
        frame = frame[joined.str.strip() != ""]

    dedupe = [col for col in spec.dedupe_columns if col in frame.columns]
    if dedupe and not frame.empty:
        frame = frame.drop_duplicates(subset=dedupe, keep="first")
    return frame[spec.columns]


def materialize_spec(root: Path, spec: SourceSpec, force: bool = False) -> dict:
    output_path = root / spec.output
    if output_path.exists() and not force:
        existing = pd.read_csv(output_path, dtype=str, na_filter=False)
        return {
            "source_id": spec.source_id,
            "status": "existing",
            "rows": int(len(existing)),
            "output": spec.output,
            "schema": spec.schema,
            "dropzone": spec.dropzone,
        }

    loaded = load_tabular_dropzone(root / spec.dropzone)
    frames = [
        map_frame(
            table.frame,
            spec.column_map,
            spec.columns,
            spec.source_id,
            table.path.name,
        )
        for table in loaded
    ]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=spec.columns)
    frame = _postprocess(spec, frame)
    missing = ensure_required_columns(frame, spec.columns)
    write_canonical_csv(frame, output_path, spec.columns)

    status = "schema_error" if missing else ("ok" if len(frame) else "empty")
    return {
        "source_id": spec.source_id,
        "status": status,
        "rows": int(len(frame)),
        "output": spec.output,
        "schema": spec.schema,
        "dropzone": spec.dropzone,
        "files_seen": len(loaded),
        "missing_columns": missing,
    }


def run(
    root: Path | str | None = None,
    sources: list[str] | None = None,
    force: bool = False,
) -> dict:
    root_path = Path(root or PROJECT_ROOT)
    selected = sources or list(SOURCE_SPECS)
    unknown = sorted(set(selected) - set(SOURCE_SPECS))
    if unknown:
        raise ValueError(f"Unknown Tranche B source key(s): {', '.join(unknown)}")

    results = [materialize_spec(root_path, SOURCE_SPECS[key], force=force) for key in selected]
    statuses = {result["status"] for result in results}
    summary = {
        "schema_version": "tranche_b_source_intake_v1",
        "status": ("prepared" if statuses <= {"ok", "empty", "existing"} else "needs_fix"),
        "sources_total": len(results),
        "sources_with_rows": sum(1 for result in results if result["rows"] > 0),
        "rows_total": sum(int(result["rows"]) for result in results),
        "materialization_promotion": "not_performed",
        "results": results,
    }
    report_path = root_path / "reports" / "tranche_b_source_intake_readiness.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Tranche B source-intake staging outputs",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCE_SPECS),
        dest="sources",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate outputs even if present",
    )
    args = parser.parse_args(argv)
    summary = run(sources=args.sources, force=args.force)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
