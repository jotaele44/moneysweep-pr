"""NGO / OSFL integration layer for Contract-Sweeper.

This module adds a first-class NGO layer without changing the existing federal
contract pipeline. It can run with partial source availability and always writes
coverage/audit outputs so islandwide blind spots remain explicit.

Expected optional source locations:
  data/raw/ngos/irs_eo_bmf/*.{csv,txt}
  data/raw/ngos/teos/*.{csv,json,jsonl}
  data/raw/ngos/pr_state_registry/*.csv
  data/raw/ngos/usaspending/*.{csv,json,jsonl}
  data/staging/processed/pr_contracts_master.csv
  data/staging/processed/master_enriched.csv

Primary outputs:
  data/staging/processed/ngos/ngos_master.csv
  data/staging/processed/ngos/ngo_alias_registry.json
  data/staging/processed/ngos/ngo_funding_edges.csv
  data/staging/processed/ngos/ngo_municipal_coverage.csv
  data/staging/processed/ngos/ngo_graph.gexf
  data/staging/processed/ngos/ngo_coverage_report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parquet_utils import pq_write

ROOT = Path(__file__).resolve().parents[1]
RAW_NGO_DIR = ROOT / "data" / "raw" / "ngos"
PROCESSED_DIR = ROOT / "data" / "staging" / "processed"
NGO_OUT_DIR = PROCESSED_DIR / "ngos"
SCHEMA_OUT_DIR = NGO_OUT_DIR / "schema"

PUERTO_RICO_BBOX = {
    "min_lon": -67.35,
    "max_lon": -65.15,
    "min_lat": 17.80,
    "max_lat": 18.60,
}

PR_MUNICIPALITIES = [
    "Adjuntas",
    "Aguada",
    "Aguadilla",
    "Aguas Buenas",
    "Aibonito",
    "Anasco",
    "Arecibo",
    "Arroyo",
    "Barceloneta",
    "Barranquitas",
    "Bayamon",
    "Cabo Rojo",
    "Caguas",
    "Camuy",
    "Canovanas",
    "Carolina",
    "Catano",
    "Cayey",
    "Ceiba",
    "Ciales",
    "Cidra",
    "Coamo",
    "Comerio",
    "Corozal",
    "Culebra",
    "Dorado",
    "Fajardo",
    "Florida",
    "Guanica",
    "Guayama",
    "Guayanilla",
    "Guaynabo",
    "Gurabo",
    "Hatillo",
    "Hormigueros",
    "Humacao",
    "Isabela",
    "Jayuya",
    "Juana Diaz",
    "Juncos",
    "Lajas",
    "Lares",
    "Las Marias",
    "Las Piedras",
    "Loiza",
    "Luquillo",
    "Manati",
    "Maricao",
    "Maunabo",
    "Mayaguez",
    "Moca",
    "Morovis",
    "Naguabo",
    "Naranjito",
    "Orocovis",
    "Patillas",
    "Penuelas",
    "Ponce",
    "Quebradillas",
    "Rincon",
    "Rio Grande",
    "Sabana Grande",
    "Salinas",
    "San German",
    "San Juan",
    "San Lorenzo",
    "San Sebastian",
    "Santa Isabel",
    "Toa Alta",
    "Toa Baja",
    "Trujillo Alto",
    "Utuado",
    "Vega Alta",
    "Vega Baja",
    "Vieques",
    "Villalba",
    "Yabucoa",
    "Yauco",
]

NGO_COLUMNS = [
    "ngo_id",
    "ein",
    "uei",
    "legal_name",
    "aliases",
    "entity_type",
    "irs_subsection",
    "ntee_code",
    "pr_corp_id",
    "status_irs",
    "status_pr",
    "address_raw",
    "municipality",
    "state",
    "lat",
    "lon",
    "coverage_municipalities",
    "source_ids",
    "confidence",
    "review_status",
]

FUNDING_EDGE_COLUMNS = [
    "edge_id",
    "source_entity",
    "target_ngo_id",
    "target_name",
    "award_id",
    "amount",
    "program",
    "funding_channel",
    "role",
    "period_start",
    "period_end",
    "municipality",
    "source_url",
    "source_file",
    "confidence",
]

ASSET_EDGE_COLUMNS = [
    "ngo_id",
    "asset_id",
    "municipality",
    "relationship_type",
    "evidence_class",
    "confidence",
]

FISCAL_SPONSOR_EDGE_COLUMNS = [
    "sponsor_ngo_id",
    "sponsored_entity",
    "relationship_type",
    "source_file",
    "confidence",
]


def ensure_dirs() -> None:
    NGO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMA_OUT_DIR.mkdir(parents=True, exist_ok=True)
    for subdir in ["irs_eo_bmf", "teos", "pr_state_registry", "usaspending"]:
        (RAW_NGO_DIR / subdir).mkdir(parents=True, exist_ok=True)


def strip_accents(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def norm_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = strip_accents(str(value)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", text)).strip()


def clean_ein(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    digits = re.sub(r"\D+", "", str(value))
    return digits.zfill(9) if digits else ""


def clean_amount(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in {"", ".", "-"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(norm_text(part) for part in parts if part not in (None, ""))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def canonical_municipality(value: object) -> str:
    text = norm_text(value)
    if not text:
        return ""
    lookup = {norm_text(m): m for m in PR_MUNICIPALITIES}
    if text in lookup:
        return lookup[text]
    for key, muni in lookup.items():
        if key in text or text in key:
            return muni
    return ""


def detect_municipality_from_row(row: pd.Series) -> str:
    candidates = [
        row.get("municipality"),
        row.get("city"),
        row.get("recipient_city_name"),
        row.get("legal_entity_city_name"),
        row.get("place_of_performance_city_name"),
        row.get("address_raw"),
        row.get("address"),
        row.get("street"),
    ]
    for candidate in candidates:
        muni = canonical_municipality(candidate)
        if muni:
            return muni
    joined = " ".join(str(x) for x in candidates if x is not None and not pd.isna(x))
    return canonical_municipality(joined)


def source_files(path: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not path.exists():
        return []
    files: list[Path] = []
    for suffix in suffixes:
        files.extend(path.glob(f"*.{suffix}"))
    return sorted(files)


def read_table_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".jsonl":
        return pd.read_json(path, lines=True)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("results", "data", "records", "organizations"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        return pd.DataFrame(data)
    if path.suffix.lower() == ".txt":
        return pd.read_csv(path, sep=None, engine="python", dtype=str)
    return pd.read_csv(path, dtype=str, low_memory=False)


def lower_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [norm_text(c).lower().replace(" ", "_") for c in df.columns]
    return df


def first_present(row: pd.Series, fields: Iterable[str]) -> object:
    for field in fields:
        if field in row and row[field] not in (None, "") and not pd.isna(row[field]):
            return row[field]
    return ""


def is_pr_row(row: pd.Series) -> bool:
    state = norm_text(
        first_present(
            row, ["state", "recipient_state_code", "legal_entity_state_code", "mailing_state"]
        )
    )
    country = norm_text(
        first_present(row, ["country", "recipient_country_code", "legal_entity_country_code"])
    )
    municipality = detect_municipality_from_row(row)
    address = norm_text(" ".join(str(v) for v in row.values if v is not None and not pd.isna(v)))
    return (
        state in {"PR", "PUERTO RICO"}
        or country in {"PR", "PRI", "USA"}
        and bool(municipality)
        or "PUERTO RICO" in address
    )


def classify_entity_type(name: str, ntee: str = "") -> str:
    text = norm_text(name)
    ntee_norm = norm_text(ntee)
    if "COOPERATIVA" in text or "COOP" in text:
        return "cooperative"
    if "IGLESIA" in text or "CHURCH" in text or ntee_norm.startswith("X"):
        return "faith_affiliated"
    if "FOUNDATION" in text or "FUNDACION" in text:
        return "foundation"
    if "UNIVERSIDAD" in text or "UNIVERSITY" in text:
        return "university_affiliated"
    if "ASOCIACION" in text or "ASSOCIATION" in text:
        return "association"
    return "nonprofit"


def source_families(row: pd.Series) -> set[str]:
    """Return the set of source families backing a row, e.g. {"irs_eo_bmf"}.

    ``source_ids`` is a JSON list like ``["irs_eo_bmf:x.csv", "teos:y.csv"]``; the
    family is the token before the first colon.
    """
    try:
        ids = json.loads(row.get("source_ids") or "[]")
    except (json.JSONDecodeError, TypeError):
        ids = []
    return {str(sid).split(":", 1)[0] for sid in ids if sid}


def score_row(row: pd.Series) -> tuple[int, str]:
    score = 0
    if row.get("ein"):
        score += 30
    if row.get("uei"):
        score += 20
    if row.get("pr_corp_id"):
        score += 20
    if row.get("status_irs") and row.get("status_irs") != "unknown":
        score += 10
    if row.get("status_pr") and row.get("status_pr") != "unknown":
        score += 10
    if row.get("municipality"):
        score += 10
    if row.get("legal_name"):
        score += 10
    # Canonical-source provenance bonus: IRS federal registries (EO BMF / TEOS)
    # and the PR state registry are authoritative identity sources, so rows backed
    # by them should not languish in the conservative `probable` band on identity
    # fields alone.
    families = source_families(row)
    if families & {"irs_eo_bmf", "teos"}:
        score += 15
    if "pr_state_registry" in families:
        score += 10
    score = min(score, 100)
    if score >= 90:
        status = "confirmed"
    elif score >= 75:
        status = "strong_probable"
    elif score >= 60:
        status = "probable"
    elif score >= 40:
        status = "needs_review"
    else:
        status = "lead_only"
    return score, status


def create_schema_files() -> None:
    ensure_dirs()
    schemas = {
        "ngos_master.schema.json": {
            "name": "ngos_master",
            "primary_key": "ngo_id",
            "columns": NGO_COLUMNS,
            "required": ["ngo_id", "legal_name", "source_ids", "confidence", "review_status"],
            "bbox": PUERTO_RICO_BBOX,
            "municipality_count_required": 78,
        },
        "ngo_funding_edges.schema.json": {
            "name": "ngo_funding_edges",
            "primary_key": "edge_id",
            "columns": FUNDING_EDGE_COLUMNS,
            "required": [
                "edge_id",
                "target_ngo_id",
                "target_name",
                "role",
                "source_file",
                "confidence",
            ],
        },
        "ngo_municipal_coverage.schema.json": {
            "name": "ngo_municipal_coverage",
            "primary_key": "municipality",
            "columns": [
                "municipality",
                "ngo_count_registered",
                "ngo_count_federally_funded",
                "ngo_count_disaster_recovery",
                "ngo_count_asset_linked",
                "unmatched_awards",
                "coverage_score",
                "blind_spot_reason",
            ],
            "required_municipalities": PR_MUNICIPALITIES,
        },
        "ngo_asset_edges.schema.json": {
            "name": "ngo_asset_edges",
            "primary_key": ["ngo_id", "asset_id"],
            "columns": ASSET_EDGE_COLUMNS,
            "required": ["ngo_id", "asset_id", "relationship_type", "evidence_class", "confidence"],
        },
        "ngo_fiscal_sponsor_edges.schema.json": {
            "name": "ngo_fiscal_sponsor_edges",
            "primary_key": ["sponsor_ngo_id", "sponsored_entity"],
            "columns": FISCAL_SPONSOR_EDGE_COLUMNS,
            "required": ["sponsor_ngo_id", "sponsored_entity", "relationship_type", "confidence"],
        },
    }
    for filename, payload in schemas.items():
        (SCHEMA_OUT_DIR / filename).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def ingest_irs_eo_bmf() -> pd.DataFrame:
    frames = []
    for path in source_files(RAW_NGO_DIR / "irs_eo_bmf", ("csv", "txt")):
        df = lower_columns(read_table_file(path))
        rows = []
        for _, row in df.iterrows():
            if not is_pr_row(row):
                continue
            name = first_present(row, ["organization_name", "name", "primary_name", "legal_name"])
            ein = clean_ein(first_present(row, ["ein", "employer_identification_number"]))
            ntee = str(first_present(row, ["ntee_code", "ntee_cd", "ntee"]) or "")
            municipality = detect_municipality_from_row(row)
            address = first_present(row, ["address", "street", "mailing_address", "address_raw"])
            rows.append(
                {
                    "ngo_id": stable_id("ngo", ein or name, municipality),
                    "ein": ein,
                    "uei": "",
                    "legal_name": str(name).strip(),
                    "aliases": json.dumps([], ensure_ascii=False),
                    "entity_type": classify_entity_type(str(name), ntee),
                    "irs_subsection": str(
                        first_present(row, ["subsection", "irc_section", "deductibility_code"])
                        or ""
                    ),
                    "ntee_code": ntee,
                    "pr_corp_id": "",
                    "status_irs": "active",
                    "status_pr": "unknown",
                    "address_raw": str(address or ""),
                    "municipality": municipality,
                    "state": "PR",
                    "lat": "",
                    "lon": "",
                    "coverage_municipalities": json.dumps(
                        [municipality] if municipality else [], ensure_ascii=False
                    ),
                    "source_ids": json.dumps([f"irs_eo_bmf:{path.name}"], ensure_ascii=False),
                    "group_exemption": str(
                        first_present(row, ["group_exemption_number", "group_exemption", "gen"])
                        or ""
                    ),
                    "affiliation": str(
                        first_present(row, ["affiliation", "affiliation_code"]) or ""
                    ),
                    "fiscal_sponsor": str(
                        first_present(row, ["fiscal_sponsor", "sponsored_by", "fiscal_agent"]) or ""
                    ),
                }
            )
        if rows:
            frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=NGO_COLUMNS)


def ingest_teos_bulk(existing: pd.DataFrame) -> pd.DataFrame:
    records = existing.copy()
    teos_rows = []
    for path in source_files(RAW_NGO_DIR / "teos", ("csv", "json", "jsonl")):
        df = lower_columns(read_table_file(path))
        for _, row in df.iterrows():
            if not is_pr_row(row):
                continue
            name = first_present(row, ["organization_name", "organization", "name", "legal_name"])
            ein = clean_ein(first_present(row, ["ein", "employer_identification_number"]))
            municipality = detect_municipality_from_row(row)
            teos_rows.append(
                {
                    "ngo_id": stable_id("ngo", ein or name, municipality),
                    "ein": ein,
                    "uei": "",
                    "legal_name": str(name).strip(),
                    "aliases": json.dumps([], ensure_ascii=False),
                    "entity_type": classify_entity_type(str(name)),
                    "irs_subsection": str(
                        first_present(row, ["subsection", "deductibility_code", "foundation_code"])
                        or ""
                    ),
                    "ntee_code": str(first_present(row, ["ntee_code", "ntee"]) or ""),
                    "pr_corp_id": "",
                    "status_irs": str(
                        first_present(row, ["status", "revocation_date"]) or "active"
                    ),
                    "status_pr": "unknown",
                    "address_raw": str(
                        first_present(row, ["address", "street", "mailing_address"]) or ""
                    ),
                    "municipality": municipality,
                    "state": "PR",
                    "lat": "",
                    "lon": "",
                    "coverage_municipalities": json.dumps(
                        [municipality] if municipality else [], ensure_ascii=False
                    ),
                    "source_ids": json.dumps([f"teos:{path.name}"], ensure_ascii=False),
                    "group_exemption": str(
                        first_present(row, ["group_exemption_number", "group_exemption", "gen"])
                        or ""
                    ),
                    "affiliation": str(
                        first_present(row, ["affiliation", "affiliation_code"]) or ""
                    ),
                    "fiscal_sponsor": str(
                        first_present(row, ["fiscal_sponsor", "sponsored_by", "fiscal_agent"]) or ""
                    ),
                }
            )
    if teos_rows:
        records = pd.concat([records, pd.DataFrame(teos_rows)], ignore_index=True)
    return records


def ingest_pr_state_registry(existing: pd.DataFrame) -> pd.DataFrame:
    records = existing.copy()
    rows = []
    for path in source_files(RAW_NGO_DIR / "pr_state_registry", ("csv",)):
        df = lower_columns(read_table_file(path))
        for _, row in df.iterrows():
            name = first_present(row, ["entity_name", "corporation_name", "name", "legal_name"])
            if not name:
                continue
            purpose = norm_text(first_present(row, ["entity_type", "class", "purpose", "category"]))
            if not any(
                token in purpose or token in norm_text(name)
                for token in ["NON", "SIN FINES", "OSFL", "FUNDACION", "ASOCIACION", "IGLESIA"]
            ):
                continue
            municipality = detect_municipality_from_row(row)
            rows.append(
                {
                    "ngo_id": stable_id("ngo", name, municipality),
                    "ein": clean_ein(first_present(row, ["ein"])),
                    "uei": "",
                    "legal_name": str(name).strip(),
                    "aliases": json.dumps([], ensure_ascii=False),
                    "entity_type": classify_entity_type(str(name)),
                    "irs_subsection": "",
                    "ntee_code": "",
                    "pr_corp_id": str(
                        first_present(
                            row, ["registry_number", "corp_id", "entity_id", "registration_number"]
                        )
                        or ""
                    ),
                    "status_irs": "unknown",
                    "status_pr": str(first_present(row, ["status", "standing"]) or "active"),
                    "address_raw": str(
                        first_present(row, ["address", "physical_address", "mailing_address"]) or ""
                    ),
                    "municipality": municipality,
                    "state": "PR",
                    "lat": "",
                    "lon": "",
                    "coverage_municipalities": json.dumps(
                        [municipality] if municipality else [], ensure_ascii=False
                    ),
                    "source_ids": json.dumps(
                        [f"pr_state_registry:{path.name}"], ensure_ascii=False
                    ),
                }
            )
    if rows:
        records = pd.concat([records, pd.DataFrame(rows)], ignore_index=True)
    return records


def consolidate_ngos(records: pd.DataFrame) -> pd.DataFrame:
    if records.empty:
        return pd.DataFrame(columns=NGO_COLUMNS)
    records = records.copy()
    for col in NGO_COLUMNS:
        if col not in records.columns:
            records[col] = ""
    records["ein"] = records["ein"].map(clean_ein)
    records["name_key"] = records["legal_name"].map(norm_text)
    records["muni_key"] = records["municipality"].map(norm_text)
    records["merge_key"] = records.apply(
        lambda r: f"ein:{r['ein']}" if r.get("ein") else f"name:{r['name_key']}|{r['muni_key']}",
        axis=1,
    )
    grouped = []
    for _, group in records.groupby("merge_key", dropna=False):
        base = group.iloc[0].to_dict()
        aliases = sorted(
            set(group["legal_name"].dropna().astype(str)) - {str(base.get("legal_name", ""))}
        )
        source_ids = []
        coverage = set()
        for _, row in group.iterrows():
            try:
                source_ids.extend(json.loads(row.get("source_ids") or "[]"))
            except json.JSONDecodeError:
                pass
            try:
                coverage.update(
                    x for x in json.loads(row.get("coverage_municipalities") or "[]") if x
                )
            except json.JSONDecodeError:
                pass
            if row.get("municipality"):
                coverage.add(row["municipality"])
            for field in [
                "uei",
                "pr_corp_id",
                "irs_subsection",
                "ntee_code",
                "address_raw",
                "municipality",
            ]:
                if not base.get(field) and row.get(field):
                    base[field] = row[field]
            if row.get("status_pr") not in ("", "unknown"):
                base["status_pr"] = row["status_pr"]
            if row.get("status_irs") not in ("", "unknown"):
                base["status_irs"] = row["status_irs"]
        base["ngo_id"] = stable_id(
            "ngo", base.get("ein") or base.get("legal_name"), base.get("municipality")
        )
        base["aliases"] = json.dumps(aliases, ensure_ascii=False)
        base["source_ids"] = json.dumps(sorted(set(source_ids)), ensure_ascii=False)
        base["coverage_municipalities"] = json.dumps(sorted(coverage), ensure_ascii=False)
        score, status = score_row(pd.Series(base))
        base["confidence"] = score
        base["review_status"] = status
        grouped.append(base)
    out = pd.DataFrame(grouped)
    return out[NGO_COLUMNS].sort_values(["municipality", "legal_name"], na_position="last")


def likely_ngo_name(name: str) -> bool:
    text = norm_text(name)
    tokens = [
        "FOUNDATION",
        "FUNDACION",
        "ASOCIACION",
        "ASSOCIATION",
        "NONPROFIT",
        "NON PROFIT",
        "COMMUNITY",
        "COMUNIDAD",
        "IGLESIA",
        "CHURCH",
        "CENTER",
        "CENTRO",
        "INSTITUTE",
        "INSTITUTO",
        "CORPORACION SIN FINES",
        "COOPERATIVA",
        "COALITION",
        "ALIANZA",
    ]
    return any(token in text for token in tokens)


def read_award_sources() -> list[tuple[str, pd.DataFrame]]:
    candidates = [
        PROCESSED_DIR / "pr_contracts_master.csv",
        PROCESSED_DIR / "master_enriched.csv",
    ]
    candidates.extend(source_files(RAW_NGO_DIR / "usaspending", ("csv", "json", "jsonl")))
    outputs: list[tuple[str, pd.DataFrame]] = []
    for path in candidates:
        if path.exists():
            outputs.append((str(path.relative_to(ROOT)), lower_columns(read_table_file(path))))
    return outputs


def join_usaspending_awards_subawards(ngos: pd.DataFrame) -> pd.DataFrame:
    edges = []
    if ngos.empty:
        return pd.DataFrame(columns=FUNDING_EDGE_COLUMNS)
    name_index = {norm_text(row.legal_name): row for row in ngos.itertuples(index=False)}
    ein_index = {row.ein: row for row in ngos.itertuples(index=False) if row.ein}
    for source_file, df in read_award_sources():
        for _, row in df.iterrows():
            recipient = str(
                first_present(
                    row,
                    [
                        "recipient_name",
                        "vendor_name",
                        "awardee_or_recipient_legal",
                        "legal_entity_name",
                        "subawardee_name",
                        "subcontractor_name",
                        "prime_awardee_name",
                    ],
                )
                or ""
            ).strip()
            if not recipient:
                continue
            ein = clean_ein(
                first_present(row, ["recipient_ein", "ein", "awardee_or_recipient_ein"])
            )
            match = None
            confidence = 0
            if ein and ein in ein_index:
                match = ein_index[ein]
                confidence = 90
            else:
                rkey = norm_text(recipient)
                if rkey in name_index:
                    match = name_index[rkey]
                    confidence = 75
                elif likely_ngo_name(recipient):
                    confidence = 45
            if match is None and confidence < 45:
                continue
            target_id = (
                getattr(
                    match, "ngo_id", stable_id("ngo", recipient, detect_municipality_from_row(row))
                )
                if match is not None
                else stable_id("ngo", recipient, detect_municipality_from_row(row))
            )
            municipality = detect_municipality_from_row(row)
            award_id = str(
                first_present(
                    row,
                    [
                        "award_id",
                        "contract_id",
                        "generated_unique_award_id",
                        "piid",
                        "subaward_number",
                    ],
                )
                or ""
            )
            amount = clean_amount(
                first_present(
                    row,
                    ["amount", "obligated_amount", "federal_action_obligation", "subaward_amount"],
                )
            )
            agency = str(
                first_present(
                    row,
                    [
                        "awarding_agency_name",
                        "agency",
                        "funding_agency_name",
                        "prime_awarding_agency_name",
                    ],
                )
                or ""
            )
            program = str(
                first_present(
                    row, ["program", "award_description", "description", "naics_description"]
                )
                or ""
            )
            role = "subrecipient" if "sub" in norm_text(" ".join(df.columns)) else "recipient"
            edges.append(
                {
                    "edge_id": stable_id("ngoedge", source_file, award_id, recipient, amount),
                    "source_entity": agency,
                    "target_ngo_id": target_id,
                    "target_name": recipient,
                    "award_id": award_id,
                    "amount": amount,
                    "program": program,
                    "funding_channel": str(
                        first_present(row, ["funding_channel", "source", "type"]) or "federal_award"
                    ),
                    "role": role,
                    "period_start": str(
                        first_present(row, ["period_start", "start_date", "award_date"]) or ""
                    ),
                    "period_end": str(first_present(row, ["period_end", "end_date"]) or ""),
                    "municipality": municipality,
                    "source_url": str(first_present(row, ["source_url", "award_url", "url"]) or ""),
                    "source_file": source_file,
                    "confidence": confidence,
                }
            )
    return (
        pd.DataFrame(edges, columns=FUNDING_EDGE_COLUMNS).drop_duplicates("edge_id")
        if edges
        else pd.DataFrame(columns=FUNDING_EDGE_COLUMNS)
    )


def _affiliation_digit(value: object) -> str:
    """Normalize an IRS affiliation code to its bare digit (e.g. "06" -> "6")."""
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits.lstrip("0") or digits


def detect_fiscal_sponsor_edges(records: pd.DataFrame) -> pd.DataFrame:
    """Derive fiscal-sponsor / umbrella relationships from the ingested NGO records.

    Two signals are used:

    1. **Declared overrides** — a hand-curated ``fiscal_sponsor`` / ``sponsored_by``
       column on a dropped-in row names the entity's umbrella explicitly.
    2. **IRS group exemptions** — organizations sharing a Group Exemption Number
       (GEN) form a group ruling. The central organization (affiliation code 6)
       is the fiscal umbrella for its subordinates (affiliation code 9).
    """
    if records is None or records.empty:
        return pd.DataFrame(columns=FISCAL_SPONSOR_EDGE_COLUMNS)

    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def source_file_of(row: pd.Series) -> str:
        try:
            ids = json.loads(row.get("source_ids") or "[]")
        except (json.JSONDecodeError, TypeError):
            ids = []
        return str(ids[0]) if ids else ""

    def emit(sponsor_id: str, sponsored: str, rel: str, src: str, conf: int) -> None:
        if not sponsor_id or not sponsored or sponsor_id == sponsored:
            return
        key = (sponsor_id, sponsored)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "sponsor_ngo_id": sponsor_id,
                "sponsored_entity": sponsored,
                "relationship_type": rel,
                "source_file": src,
                "confidence": conf,
            }
        )

    # 1. Declared overrides.
    for _, row in records.iterrows():
        declared = str(
            first_present(row, ["fiscal_sponsor", "sponsored_by", "fiscal_agent"]) or ""
        ).strip()
        if not declared:
            continue
        sponsor_id = stable_id("ngo", declared, row.get("municipality"))
        emit(
            sponsor_id,
            str(row.get("ngo_id") or ""),
            "declared_fiscal_sponsor",
            source_file_of(row),
            80,
        )

    # 2. IRS group exemptions.
    work = records.copy()
    if "group_exemption" not in work.columns:
        work["group_exemption"] = ""
    work["gen_key"] = work["group_exemption"].map(
        lambda v: re.sub(r"\D+", "", str(v or "")).lstrip("0")
    )
    for gen, group in work.groupby("gen_key", dropna=False):
        if not gen or len(group) < 2:
            continue
        centrals = [
            r for _, r in group.iterrows() if _affiliation_digit(r.get("affiliation")) == "6"
        ]
        subordinates = [
            r for _, r in group.iterrows() if _affiliation_digit(r.get("affiliation")) == "9"
        ]
        for central in centrals:
            for sub in subordinates:
                emit(
                    str(central.get("ngo_id") or ""),
                    str(sub.get("ngo_id") or ""),
                    "group_exemption",
                    source_file_of(sub),
                    70,
                )

    return pd.DataFrame(edges, columns=FISCAL_SPONSOR_EDGE_COLUMNS)


def detect_asset_edges(ngos: pd.DataFrame, funding_edges: pd.DataFrame) -> pd.DataFrame:
    """Link funded NGOs to infrastructure assets/projects.

    Reuses award/asset identifiers already present in the award sources and in the
    pipeline's execution-chain and FEMA PA masters rather than inventing new joins.
    An NGO is asset-linked when one of its funding edges resolves to a known
    asset/project id, either by award id (strong) or by normalized recipient name +
    municipality (weaker).
    """
    if funding_edges is None or funding_edges.empty:
        return pd.DataFrame(columns=ASSET_EDGE_COLUMNS)

    asset_fields = ["asset_id", "project_id", "pw_number", "disaster_number", "facility_id"]
    recipient_fields = [
        "recipient_name",
        "vendor_name",
        "awardee_or_recipient_legal",
        "legal_entity_name",
        "subawardee_name",
        "subcontractor_name",
        "prime_awardee_name",
        "sub_name",
        "prime_name",
    ]
    award_id_fields = [
        "award_id",
        "contract_id",
        "generated_unique_award_id",
        "piid",
        "subaward_number",
        "subaward_id",
        "chain_id",
    ]

    by_award: dict[str, set[tuple[str, str]]] = {}
    by_name_muni: dict[tuple[str, str], set[tuple[str, str]]] = {}

    def index_row(row: pd.Series) -> None:
        asset = str(first_present(row, asset_fields) or "").strip()
        if not asset:
            return
        muni = detect_municipality_from_row(row)
        award_id = str(first_present(row, award_id_fields) or "").strip()
        name_key = norm_text(first_present(row, recipient_fields))
        if award_id:
            by_award.setdefault(award_id, set()).add((asset, muni))
        if name_key:
            by_name_muni.setdefault((name_key, muni), set()).add((asset, muni))

    for _source_file, df in read_award_sources():
        for _, row in df.iterrows():
            index_row(row)

    for rel in ["execution/execution_chain_master.csv", "pr_fema_pa_master.csv"]:
        path = PROCESSED_DIR / rel
        if path.exists():
            df = lower_columns(read_table_file(path))
            for _, row in df.iterrows():
                index_row(row)

    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def emit(ngo_id: str, asset_id: str, muni: str, rel: str, evidence: str, conf: int) -> None:
        key = (ngo_id, asset_id)
        if not ngo_id or not asset_id or key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "ngo_id": ngo_id,
                "asset_id": asset_id,
                "municipality": muni,
                "relationship_type": rel,
                "evidence_class": evidence,
                "confidence": conf,
            }
        )

    for _, fe in funding_edges.iterrows():
        ngo_id = str(fe.get("target_ngo_id") or "").strip()
        if not ngo_id:
            continue
        award_id = str(fe.get("award_id") or "").strip()
        muni = str(fe.get("municipality") or "").strip()
        name_key = norm_text(fe.get("target_name"))
        for asset, amuni in by_award.get(award_id, set()):
            emit(ngo_id, asset, muni or amuni, "executes", "award_id_match", 80)
        for asset, amuni in by_name_muni.get((name_key, muni), set()):
            emit(ngo_id, asset, muni or amuni, "funded_at", "name_muni_match", 55)

    return pd.DataFrame(edges, columns=ASSET_EDGE_COLUMNS)


def build_78_municipality_coverage_matrix(
    ngos: pd.DataFrame, edges: pd.DataFrame, asset_edges: pd.DataFrame | None = None
) -> pd.DataFrame:
    rows = []
    funded_ids = set(edges["target_ngo_id"].dropna().astype(str)) if not edges.empty else set()
    has_assets = asset_edges is not None and not asset_edges.empty
    recovery_terms = re.compile(r"FEMA|HUD|CDBG|DISASTER|RECOVERY|HURRICANE|MARIA|COR3", re.I)
    for muni in PR_MUNICIPALITIES:
        registered = ngos[ngos["municipality"] == muni] if not ngos.empty else pd.DataFrame()
        funded_edges = edges[edges["municipality"] == muni] if not edges.empty else pd.DataFrame()
        muni_assets = (
            asset_edges[asset_edges["municipality"] == muni] if has_assets else pd.DataFrame()
        )
        asset_linked = int(muni_assets["ngo_id"].nunique()) if not muni_assets.empty else 0
        registered_funded = (
            registered[registered["ngo_id"].isin(funded_ids)]
            if not registered.empty
            else pd.DataFrame()
        )
        disaster = (
            funded_edges[
                funded_edges.apply(
                    lambda r: bool(recovery_terms.search(" ".join(str(x) for x in r.values))),
                    axis=1,
                )
            ]
            if not funded_edges.empty
            else pd.DataFrame()
        )
        score = 0
        if len(registered) > 0:
            score += 45
        if len(registered_funded) > 0 or len(funded_edges) > 0:
            score += 35
        if len(disaster) > 0:
            score += 10
        if len(registered) > 0 and registered["confidence"].astype(float).max() >= 75:
            score += 10
        if score == 0:
            reason = "no_registered_or_funded_ngo_detected"
        elif len(registered) == 0 and len(funded_edges) > 0:
            reason = "funding_detected_but_no_registry_match"
        elif len(registered) > 0 and len(funded_edges) == 0:
            reason = "registered_ngos_no_funding_edge_yet"
        else:
            reason = "covered"
        rows.append(
            {
                "municipality": muni,
                "ngo_count_registered": int(len(registered)),
                "ngo_count_federally_funded": int(
                    len(registered_funded) + max(0, len(funded_edges) - len(registered_funded))
                ),
                "ngo_count_disaster_recovery": int(len(disaster)),
                "ngo_count_asset_linked": asset_linked,
                "unmatched_awards": int(
                    len(
                        funded_edges[~funded_edges["target_ngo_id"].isin(set(registered["ngo_id"]))]
                    )
                )
                if not funded_edges.empty and not registered.empty
                else int(len(funded_edges))
                if not funded_edges.empty
                else 0,
                "coverage_score": min(score, 100),
                "blind_spot_reason": reason,
            }
        )
    return pd.DataFrame(rows)


def export_alias_registry(ngos: pd.DataFrame) -> None:
    registry = {}
    for _, row in ngos.iterrows():
        aliases = []
        try:
            aliases = json.loads(row.get("aliases") or "[]")
        except json.JSONDecodeError:
            aliases = []
        registry[row["ngo_id"]] = {
            "legal_name": row.get("legal_name", ""),
            "name_key": norm_text(row.get("legal_name", "")),
            "aliases": aliases,
            "ein": row.get("ein", ""),
            "uei": row.get("uei", ""),
            "municipality": row.get("municipality", ""),
        }
    (NGO_OUT_DIR / "ngo_alias_registry.json").write_text(
        json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def export_graph_layer(ngos: pd.DataFrame, edges: pd.DataFrame) -> None:
    nodes: dict[str, dict[str, str]] = {}
    graph_edges = []
    for _, row in ngos.iterrows():
        nodes[row["ngo_id"]] = {"label": row.get("legal_name", row["ngo_id"]), "type": "ngo"}
        muni = row.get("municipality", "")
        if muni:
            muni_id = stable_id("muni", muni)
            nodes[muni_id] = {"label": muni, "type": "municipality"}
            graph_edges.append(
                (stable_id("edge", row["ngo_id"], muni_id), row["ngo_id"], muni_id, "located_in")
            )
    for _, row in edges.iterrows():
        agency = row.get("source_entity", "") or "Unknown Funder"
        agency_id = stable_id("funder", agency)
        nodes[agency_id] = {"label": agency, "type": "funder"}
        target_id = row.get("target_ngo_id", "")
        if target_id:
            if target_id not in nodes:
                nodes[target_id] = {"label": row.get("target_name", target_id), "type": "ngo_lead"}
            graph_edges.append(
                (
                    row.get("edge_id", stable_id("edge", agency_id, target_id)),
                    agency_id,
                    target_id,
                    row.get("role", "funds"),
                )
            )
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gexf xmlns="http://www.gexf.net/1.2draft" version="1.2">',
        '  <graph mode="static" defaultedgetype="directed">',
        "    <nodes>",
    ]
    for node_id, attrs in nodes.items():
        lines.append(
            f'      <node id="{escape(node_id)}" label="{escape(attrs["label"])}"><attvalues><attvalue for="type" value="{escape(attrs["type"])}"/></attvalues></node>'
        )
    lines.extend(["    </nodes>", "    <edges>"])
    for idx, (edge_id, src, dst, label) in enumerate(graph_edges):
        lines.append(
            f'      <edge id="{escape(edge_id or str(idx))}" source="{escape(src)}" target="{escape(dst)}" label="{escape(str(label))}" />'
        )
    lines.extend(["    </edges>", "  </graph>", "</gexf>"])
    (NGO_OUT_DIR / "ngo_graph.gexf").write_text("\n".join(lines), encoding="utf-8")


def write_review_outputs(
    ngos: pd.DataFrame,
    edges: pd.DataFrame,
    coverage: pd.DataFrame,
    asset_edges: pd.DataFrame | None = None,
    fiscal_edges: pd.DataFrame | None = None,
) -> None:
    review = (
        ngos[ngos["review_status"].isin(["needs_review", "lead_only"])]
        if not ngos.empty
        else pd.DataFrame(columns=NGO_COLUMNS)
    )
    review.to_csv(NGO_OUT_DIR / "ngo_review_queue.csv", index=False)
    duplicates = (
        ngos[ngos.duplicated(["legal_name", "municipality"], keep=False)]
        if not ngos.empty
        else pd.DataFrame(columns=NGO_COLUMNS)
    )
    duplicates.to_csv(NGO_OUT_DIR / "ngo_duplicate_candidates.csv", index=False)
    disaster = (
        edges[
            edges.apply(
                lambda r: bool(
                    re.search(
                        r"FEMA|HUD|CDBG|DISASTER|RECOVERY|HURRICANE|MARIA|COR3",
                        " ".join(str(x) for x in r.values),
                        re.I,
                    )
                ),
                axis=1,
            )
        ]
        if not edges.empty
        else pd.DataFrame(columns=FUNDING_EDGE_COLUMNS)
    )
    disaster.to_csv(NGO_OUT_DIR / "ngo_disaster_recovery_exposure.csv", index=False)
    if asset_edges is None:
        asset_edges = pd.DataFrame(columns=ASSET_EDGE_COLUMNS)
    if fiscal_edges is None:
        fiscal_edges = pd.DataFrame(columns=FISCAL_SPONSOR_EDGE_COLUMNS)
    asset_edges.to_csv(NGO_OUT_DIR / "ngo_asset_edges.csv", index=False)
    fiscal_edges.to_csv(NGO_OUT_DIR / "ngo_fiscal_sponsor_edges.csv", index=False)
    pq_write(asset_edges, NGO_OUT_DIR / "ngo_asset_edges.parquet")
    pq_write(fiscal_edges, NGO_OUT_DIR / "ngo_fiscal_sponsor_edges.parquet")
    report = [
        "# NGO Integration Coverage Report",
        "",
        f"NGO records: {len(ngos)}",
        f"Funding edges: {len(edges)}",
        f"Municipalities covered in matrix: {coverage['municipality'].nunique() if not coverage.empty else 0}/78",
        f"Municipalities with registered NGOs: {int((coverage['ngo_count_registered'] > 0).sum()) if not coverage.empty else 0}",
        f"Municipalities with funding edges: {int((coverage['ngo_count_federally_funded'] > 0).sum()) if not coverage.empty else 0}",
        "",
        "## Open Blind Spots",
        "",
    ]
    if not coverage.empty:
        blind = coverage[coverage["blind_spot_reason"] != "covered"]
        for _, row in blind.iterrows():
            report.append(
                f"- {row['municipality']}: {row['blind_spot_reason']} (score={row['coverage_score']})"
            )
    (NGO_OUT_DIR / "ngo_coverage_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def run_pipeline() -> dict[str, object]:
    ensure_dirs()
    create_schema_files()
    records = ingest_irs_eo_bmf()
    records = ingest_teos_bulk(records)
    records = ingest_pr_state_registry(records)
    ngos = consolidate_ngos(records)
    funding_edges = join_usaspending_awards_subawards(ngos)
    asset_edges = detect_asset_edges(ngos, funding_edges)
    fiscal_edges = detect_fiscal_sponsor_edges(records)
    coverage = build_78_municipality_coverage_matrix(ngos, funding_edges, asset_edges)
    ngos.to_csv(NGO_OUT_DIR / "ngos_master.csv", index=False)
    funding_edges.to_csv(NGO_OUT_DIR / "ngo_funding_edges.csv", index=False)
    coverage.to_csv(NGO_OUT_DIR / "ngo_municipal_coverage.csv", index=False)
    pq_write(ngos, NGO_OUT_DIR / "ngos_master.parquet")
    pq_write(funding_edges, NGO_OUT_DIR / "ngo_funding_edges.parquet")
    pq_write(coverage, NGO_OUT_DIR / "ngo_municipal_coverage.parquet")
    export_alias_registry(ngos)
    export_graph_layer(ngos, funding_edges)
    write_review_outputs(ngos, funding_edges, coverage, asset_edges, fiscal_edges)
    summary = {
        "ngos": int(len(ngos)),
        "funding_edges": int(len(funding_edges)),
        "asset_edges": int(len(asset_edges)),
        "fiscal_sponsor_edges": int(len(fiscal_edges)),
        "municipalities": int(coverage["municipality"].nunique()),
        "output_dir": str(NGO_OUT_DIR.relative_to(ROOT)),
        "status": "pass" if coverage["municipality"].nunique() == 78 else "fail",
    }
    (NGO_OUT_DIR / "ngo_validation_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build NGO / OSFL integration layer for Contract-Sweeper"
    )
    parser.add_argument("--schema-only", action="store_true", help="Write NGO schema files only")
    args = parser.parse_args()
    if args.schema_only:
        ensure_dirs()
        create_schema_files()
        print(
            json.dumps(
                {
                    "status": "pass",
                    "mode": "schema-only",
                    "output_dir": str(SCHEMA_OUT_DIR.relative_to(ROOT)),
                },
                indent=2,
            )
        )
        return
    print(json.dumps(run_pipeline(), indent=2))


if __name__ == "__main__":
    main()
