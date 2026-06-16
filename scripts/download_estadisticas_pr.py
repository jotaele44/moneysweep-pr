"""Instituto de Estadísticas de PR (Datos.PR CKAN) fiscal-revenue producer.

Fetches PR fiscal-revenue datasets from the standard **CKAN** API at
``https://datos.estadisticas.pr`` and materializes canonical CSVs. One estadisticas
portal feeds two registry sources:

  - ``pr_general_fund_revenues``  <- "Ingresos Netos al Fondo General"
                                     (General Fund net revenues by source / period —
                                     covers Act 154, income tax, IVU, arbitrios,
                                     licenses, lottery, customs, rum cover-over)
  - ``pr_income_tax_collections`` <- income-tax contribution series (individual +
                                     corporate)
  - ``estadisticas_pr_external_trade`` <- PR external-trade series (imports / exports)

CKAN access (no API key): ``package_search`` resolves the dataset by name, then
``datastore_search`` (paginated) pulls the active datastore resource; if the resource
is a plain CSV instead, it is downloaded and parsed. Field names vary by dataset, so a
tolerant alias map projects them onto a stable canonical schema.

No-egress safe: any network/HTTP failure (e.g. the buildout sandbox has no egress)
writes an empty-schema CSV and returns ``status="EMPTY"`` without raising — the
readiness preflight imports this module without touching the network.

Usage:
  python3 scripts/download_estadisticas_pr.py                       # both sources
  python3 scripts/download_estadisticas_pr.py --source pr_general_fund_revenues
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from scripts.config import PROJECT_ROOT, setup_logging

CKAN_BASE = "https://datos.estadisticas.pr"
USER_AGENT = "ContractSweeper/1.0 (+https://github.com/jotaele44/Contract-Sweeper)"
MAX_RETRIES = 3
RETRY_BACKOFF = (5, 15, 30)
PAGE_LIMIT = 1000
MAX_RECORDS = 200_000  # safety cap

# Canonical output schema (shared by both sources; deterministic, no timestamps).
CANONICAL_COLUMNS = ["period", "category", "amount_usd", "source_system"]

# Tolerant field aliases (Spanish/English) mapping a raw CKAN record onto the schema.
PERIOD_ALIASES = (
    "period",
    "periodo",
    "fecha",
    "ano_fiscal",
    "año_fiscal",
    "year",
    "ano",
    "año",
    "mes",
    "month",
)
CATEGORY_ALIASES = (
    "category",
    "categoria",
    "categoría",
    "fuente",
    "concepto",
    "renglon",
    "renglón",
    "descripcion",
    "descripción",
    "partida",
)
AMOUNT_ALIASES = (
    "amount_usd",
    "amount",
    "ingresos_netos",
    "ingreso_neto",
    "monto",
    "cantidad",
    "valor",
    "recaudo",
    "recaudos",
    "total",
)

# source_id -> CKAN dataset discovery query.
SOURCES = {
    "pr_general_fund_revenues": {
        "query": "ingresos netos fondo general",
        "output": "data/staging/processed/pr_general_fund_revenues.csv",
    },
    "pr_income_tax_collections": {
        "query": "contribucion sobre ingresos",
        "output": "data/staging/processed/pr_income_tax_collections.csv",
    },
    "estadisticas_pr_external_trade": {
        "query": "comercio externo importaciones exportaciones",
        "output": "data/staging/processed/pr_external_trade.csv",
    },
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _get_json(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    """GET JSON with retry/backoff. Returns None on any terminal failure (no raise)."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt + 1} failed ({exc}) — retry in {wait}s")
                time.sleep(wait)
            else:
                logger.warning(f"  All {MAX_RETRIES} attempts failed for {url}: {exc}")
    return None


def _ckan_action(session, base: str, action: str, params: dict, logger) -> dict | list | None:
    payload = _get_json(session, f"{base}/api/3/action/{action}", params, logger)
    if not payload or not payload.get("success"):
        return None
    return payload.get("result")


def _resolve_resource(session, base: str, query: str, logger) -> dict | None:
    """package_search for the dataset; return the best fetchable resource (datastore or CSV)."""
    result = _ckan_action(session, base, "package_search", {"q": query, "rows": 5}, logger)
    if not result or not isinstance(result, dict):
        return None
    for pkg in result.get("results", []):
        resources = pkg.get("resources", [])
        # Prefer a datastore-active resource; fall back to a CSV resource.
        for res in resources:
            if res.get("datastore_active"):
                return res
        for res in resources:
            if (res.get("format") or "").lower() == "csv" and res.get("url"):
                return res
    return None


def _fetch_datastore(session, base: str, resource_id: str, logger) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while offset < MAX_RECORDS:
        result = _ckan_action(
            session,
            base,
            "datastore_search",
            {"resource_id": resource_id, "limit": PAGE_LIMIT, "offset": offset},
            logger,
        )
        if not result or not isinstance(result, dict):
            break
        records = result.get("records", [])
        if not records:
            break
        rows.extend(records)
        offset += len(records)
        if len(records) < PAGE_LIMIT or offset >= int(result.get("total", offset)):
            break
        time.sleep(0.3)
    return rows


def _fetch_csv(session, url: str, logger) -> list[dict]:
    try:
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(f"  CSV download failed ({exc})")
        return []
    return list(csv.DictReader(io.StringIO(resp.text)))


def _pick(record: dict, aliases: tuple[str, ...]) -> str:
    lower = {str(k).strip().lower(): v for k, v in record.items()}
    for alias in aliases:
        if alias in lower and lower[alias] not in (None, ""):
            return str(lower[alias]).strip()
    return ""


def _clean_amount(value: str) -> str:
    s = value.replace("$", "").replace(",", "").strip()
    if s in ("", "-", "—"):
        return ""
    try:
        return str(float(s))
    except ValueError:
        return ""


def _normalize(records: list[dict], source_id: str) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        row = {
            "period": _pick(rec, PERIOD_ALIASES),
            "category": _pick(rec, CATEGORY_ALIASES),
            "amount_usd": _clean_amount(_pick(rec, AMOUNT_ALIASES)),
            "source_system": source_id,
        }
        if not row["period"] and not row["category"] and not row["amount_usd"]:
            continue
        out.append(row)
    out.sort(key=lambda r: (r["period"], r["category"], r["amount_usd"]))
    return out


def _write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def materialize_source(root: Path, source_id: str, session, logger) -> dict:
    cfg = SOURCES[source_id]
    out_path = root / cfg["output"]
    resource = _resolve_resource(session, CKAN_BASE, cfg["query"], logger)
    records: list[dict] = []
    if resource:
        if resource.get("datastore_active"):
            records = _fetch_datastore(session, CKAN_BASE, resource["id"], logger)
        elif resource.get("url"):
            records = _fetch_csv(session, resource["url"], logger)
    rows = _normalize(records, source_id)
    _write_csv(rows, out_path)
    status = "OK" if rows else "EMPTY"
    if not rows:
        logger.info(f"  [{source_id}] no records (no egress / dataset not found) — EMPTY")
    else:
        logger.info(f"  [{source_id}] {len(rows)} rows → {cfg['output']}")
    return {"source": source_id, "rows": len(rows), "status": status, "path": str(out_path)}


def run(root: Path | None = None, source: str | None = None) -> dict:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("download_estadisticas_pr")
    keys = [source] if source else list(SOURCES)
    session = _session()
    try:
        results = [materialize_source(root, k, session, logger) for k in keys]
    finally:
        session.close()
    total = sum(r["rows"] for r in results)
    return {"rows": total, "status": "OK" if total else "EMPTY", "sources": results}


# Entrypoint aliases recognized by the pipeline readiness preflight.
main = run
download = run
fetch = run


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=list(SOURCES), default=None)
    args = parser.parse_args(argv)
    result = run(source=args.source)
    print(f"estadisticas_pr: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
