"""Download Puerto Rico corporate-identity records from GLEIF (keyless, free).

GLEIF (Global Legal Entity Identifier Foundation) publishes the open LEI
database. For PR it yields the larger / financial / bond-issuing entities
(banks, COFINA, utilities, large corps) with legal name, status, legal form,
the local registration number (``registeredAs``), addresses, and — where filed —
direct/ultimate parent relationships. This is the free replacement for the
(paid) OpenCorporates corporate-identity slice; full small-company coverage
still comes from the operator-supplied PR Dept of State export
(``scripts/ingest_active_contractors.py``).

No API key required.

Outputs:
  data/staging/processed/pr_gleif_entities.csv
  data/staging/processed/pr_gleif_relationships.csv

Usage:
  python3 scripts/download_gleif.py
  python3 scripts/download_gleif.py --no-relationships   # entities only (fast)
  python3 scripts/download_gleif.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging
from contract_sweeper.runtime.base_downloader import (
    HttpConfig,
    build_session,
    http_get_json,
)

GLEIF_BASE = "https://api.gleif.org/api/v1"
LEI_RECORDS = f"{GLEIF_BASE}/lei-records"
PAGE_SIZE = 200
MAX_PAGES = 50  # 50 * 200 = 10k headroom; PR is ~500

# GLEIF can file a PR entity under either the address country or the ISO-3166-2
# jurisdiction code, so union both filters and de-dupe by LEI (guards undercount).
PR_FILTERS = [
    {"filter[entity.legalAddress.country]": "PR"},
    {"filter[entity.jurisdiction]": "US-PR"},
]

ENTITY_COLUMNS = [
    "lei",
    "legal_name",
    "other_names",
    "jurisdiction",
    "legal_form",
    "entity_status",
    "registered_as",
    "legal_address",
    "hq_address",
    "registration_date",
    "source_url",
]
RELATIONSHIP_COLUMNS = [
    "lei",
    "legal_name",
    "relationship_type",
    "parent_lei",
    "parent_name",
]

# Quiet, count-light HTTP: small inter-page sleep, modest retries.
_HTTP = HttpConfig(page_sleep=0.1, rate_limit_sleep=20.0, max_retries=3)


def _fmt_address(addr: dict | None) -> str:
    if not addr:
        return ""
    parts = list(addr.get("addressLines") or [])
    for k in ("city", "region", "postalCode", "country"):
        v = addr.get(k)
        if v:
            parts.append(str(v))
    return ", ".join(p for p in parts if p)


def _map_entity(record: dict) -> dict:
    attrs = record.get("attributes", {}) or {}
    ent = attrs.get("entity", {}) or {}
    lei = attrs.get("lei", "")
    other = ent.get("otherNames") or []
    return {
        "lei": lei,
        "legal_name": (ent.get("legalName") or {}).get("name", ""),
        "other_names": "; ".join(o.get("name", "") for o in other if o.get("name")),
        "jurisdiction": ent.get("jurisdiction", ""),
        "legal_form": (ent.get("legalForm") or {}).get("id", ""),
        "entity_status": ent.get("status", ""),
        "registered_as": ent.get("registeredAs", ""),
        "legal_address": _fmt_address(ent.get("legalAddress")),
        "hq_address": _fmt_address(ent.get("headquartersAddress")),
        "registration_date": ent.get("creationDate", "") or "",
        "source_url": f"https://search.gleif.org/#/record/{lei}",
    }


def _fetch_entities(session, logger) -> list[dict]:
    """Paginate both PR filters, de-dupe by LEI, return mapped entity rows."""
    by_lei: dict[str, dict] = {}
    for filt in PR_FILTERS:
        page = 1
        while page <= MAX_PAGES:
            params = {**filt, "page[size]": PAGE_SIZE, "page[number]": page}
            data = http_get_json(session, LEI_RECORDS, params, logger=logger, config=_HTTP)
            if not data:
                break
            records = data.get("data") or []
            for rec in records:
                row = _map_entity(rec)
                if row["lei"]:
                    by_lei[row["lei"]] = row
            pag = (data.get("meta") or {}).get("pagination") or {}
            last = int(pag.get("lastPage", page))
            logger.info(
                "  %s page %d/%d (+%d, total unique=%d)",
                list(filt.values())[0],
                page,
                last,
                len(records),
                len(by_lei),
            )
            if page >= last or not records:
                break
            page += 1
    return list(by_lei.values())


def _quiet_get(session, url: str) -> dict | None:
    """Direct GET that treats 404 (no such relationship) as a normal empty."""
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:  # noqa: BLE001
        return None


def _fetch_relationships(session, entities: list[dict], logger) -> list[dict]:
    """Best-effort direct/ultimate parents per LEI. Sparse for PR; never fatal."""
    rows: list[dict] = []
    for i, ent in enumerate(entities, 1):
        lei = ent["lei"]
        for rel_type, slug in (
            ("direct_parent", "direct-parent"),
            ("ultimate_parent", "ultimate-parent"),
        ):
            data = _quiet_get(session, f"{LEI_RECORDS}/{lei}/{slug}")
            parent = (data or {}).get("data") or {}
            pattrs = parent.get("attributes", {}) or {}
            plei = pattrs.get("lei", "")
            if plei:
                rows.append(
                    {
                        "lei": lei,
                        "legal_name": ent["legal_name"],
                        "relationship_type": rel_type,
                        "parent_lei": plei,
                        "parent_name": (pattrs.get("entity", {}).get("legalName") or {}).get(
                            "name", ""
                        ),
                    }
                )
        if i % 100 == 0:
            logger.info("  relationships: %d/%d entities checked", i, len(entities))
    return rows


def _write(df_cols: list[str], rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=df_cols) if rows else pd.DataFrame(columns=df_cols)
    df.to_csv(path, index=False, encoding="utf-8")


def run(root: Path | None = None, force: bool = False, with_relationships: bool = True) -> dict:
    root = Path(root) if root else PROJECT_ROOT
    out_dir = root / "data" / "staging" / "processed"
    ent_path = out_dir / "pr_gleif_entities.csv"
    rel_path = out_dir / "pr_gleif_relationships.csv"
    logger = setup_logging("download_gleif")

    if not force and ent_path.exists() and ent_path.stat().st_size > 0:
        try:
            n = len(pd.read_csv(ent_path, dtype=str))
            if n > 0:
                logger.info("  pr_gleif_entities.csv exists (%d rows) — skipping.", n)
                return {"entities": n, "status": "CACHED", "path": str(ent_path)}
        except Exception:  # noqa: BLE001
            pass

    session = build_session()
    logger.info("Fetching PR LEI entities from GLEIF (keyless)...")
    entities = _fetch_entities(session, logger)

    relationships: list[dict] = []
    if entities and with_relationships:
        logger.info("Fetching parent relationships for %d entities (best-effort)...", len(entities))
        try:
            relationships = _fetch_relationships(session, entities, logger)
        except Exception as exc:  # noqa: BLE001
            logger.warning("  relationship fetch failed (non-fatal): %s", exc)

    session.close()
    _write(ENTITY_COLUMNS, entities, ent_path)
    _write(RELATIONSHIP_COLUMNS, relationships, rel_path)

    status = "OK" if entities else "EMPTY"
    if not entities:
        logger.warning("  GLEIF returned no PR entities (API unavailable?). Wrote headers only.")
    logger.info("=" * 60)
    logger.info("GLEIF DOWNLOAD SUMMARY")
    logger.info("  PR entities:      %d", len(entities))
    logger.info("  Parent relations: %d", len(relationships))
    return {
        "entities": len(entities),
        "relationships": len(relationships),
        "status": status,
        "entities_path": str(ent_path),
        "relationships_path": str(rel_path),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Download PR corporate identity from GLEIF (keyless).")
    p.add_argument("--force", action="store_true", help="Re-download even if cached.")
    p.add_argument(
        "--no-relationships", action="store_true", help="Skip parent-relationship calls."
    )
    a = p.parse_args()
    result = run(force=a.force, with_relationships=not a.no_relationships)
    print(
        f"\nGLEIF: {result['entities']:,} PR entities, "
        f"{result.get('relationships', 0):,} parent relationships. [{result['status']}]"
    )
    return 0 if result["status"] in ("OK", "EMPTY", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
