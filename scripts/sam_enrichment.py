"""
SAM.gov UEI Batch Enrichment — PR Contracts Master

Resolves vendor UEI/CAGE/DUNS from SAM.gov Entity Information API v2,
with USASpending.gov as a fallback for vendors not found in SAM.

Sources:
  Primary:  https://api.sam.gov/entity-information/v2/entities
  Fallback: https://api.usaspending.gov/api/v2/recipient/search/

API key: read from SAM_API_KEY env var or .env file (never committed to git).

Usage:
  python3 scripts/sam_enrichment.py               # full run
  python3 scripts/sam_enrichment.py --resume      # resume from checkpoint
  python3 scripts/sam_enrichment.py --dry-run     # validate config only
  python3 scripts/sam_enrichment.py --top 500     # first 500 vendors by value
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests as _requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.alias_overrides import apply as apply_override
from moneysweep.runtime.alias_overrides import load_overrides
from scripts.config import (
    PROJECT_ROOT,
    get_sam_api_key,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAM_BASE_URL = "https://api.sam.gov/entity-information/v2/entities"
USAS_BASE_URL = "https://api.usaspending.gov/api/v2/recipient/search/"

BATCH_SIZE = 25
RATE_DELAY = 0.4
RETRY_MAX = 2  # was 3 — reduces timeout waste on failed lookups
RETRY_DELAY = 1.0  # was 2.0
# 0.85 → 0.80: PR vendor names in the source data are noisy (accents, DBA
# variants, punctuation), so real matches routinely landed at 0.80–0.84 and were
# discarded. Paired with accent-folding in normalize_vendor() below.
MATCH_THRESHOLD = 0.80
COVERAGE_GATE = 0.60

# Reason codes recorded in the `resolution_status` column. They separate the
# three cases the old single "UNRESOLVED" bucket conflated: a genuine miss in the
# federal registries (expected for PR/local entities), a transient lookup error
# that should be retried, and the various resolved sources.
STATUS_RESOLVED_SAM = "RESOLVED_SAM"
STATUS_RESOLVED_USAS = "RESOLVED_USASPENDING"
STATUS_RESOLVED_SOURCE_UEI = "RESOLVED_SOURCE_UEI"
STATUS_RESOLVED_SAM_BULK = "RESOLVED_SAM_BULK"
STATUS_RESOLVED_LOCAL_GOV = "RESOLVED_LOCAL_GOV"
STATUS_DEFERRED_API = "DEFERRED_API"
STATUS_NO_FEDERAL_MATCH = "NO_FEDERAL_MATCH"
STATUS_LOOKUP_ERROR = "LOOKUP_ERROR"

MUNICIPIO_CROSSWALK = "data/reference/pr_78_municipio_crosswalk.csv"

STRIP_SUFFIXES = [
    r"\bINC\.?\b",
    r"\bCORP\.?\b",
    r"\bLLC\.?\b",
    r"\bLLP\.?\b",
    r"\bL\.P\.?\b",
    r"\bS\.E\.?\b",
    r"\bS\.P\.?\b",
    r"\bPSC\.?\b",
    r"\bLTD\.?\b",
    r"\bCO\.?\b",
    r"\bCOMPANY\b",
    r"\bCORPORATION\b",
    r"\bINCORPORATED\b",
    r"\bLIMITED\b",
    r"\bAUTHORITY\b",
    r"\bASSOCIATES\b",
    r"\bENTERPRISES\b",
    r"\bGROUP\b",
    r"\bSERVICES\b",
    r"\bSOLUTIONS\b",
    r"\bINTERNATIONAL\b",
    r"\bCONSTRUCTION\b",
    r"\bCONTRACTORS?\b",
    r"\bCONSULTANTS?\b",
]

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

_SUFFIX_EXPANSIONS = {
    r"\bINCORPORATED\b": "INC",
    r"\bCORPORATION\b": "CORP",
    r"\bCOMPANY\b": "CO",
    r"\bLIMITED\b": "LTD",
    r"\bAUTHORITY\b": "AUTH",
}


def normalize_vendor(name: str) -> str:
    """Canonical normalization: fold accents, upper, strip punctuation, expand
    then strip legal suffixes.

    NFKD accent-folding (``AUTÓNOMO`` → ``AUTONOMO``) is applied first so Spanish
    source names line up with SAM.gov's ASCII legal names — without it, accented
    vendors could never match and were logged as ``not resolved``.
    """
    n = unicodedata.normalize("NFKD", str(name))
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.upper().strip()
    n = re.sub(r"[,.\-/&'()]", " ", n)
    # Expand verbose forms before stripping so both map to the same root
    for pat, repl in _SUFFIX_EXPANSIONS.items():
        n = re.sub(pat, repl, n, flags=re.IGNORECASE)
    for pat in STRIP_SUFFIXES:
        n = re.sub(pat, " ", n, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", n).strip()


def name_similarity(a: str, b: str) -> float:
    """
    Hybrid similarity: Jaccard token-set + rapidfuzz token_set_ratio.
    rapidfuzz handles abbreviations and short names that Jaccard misses
    (e.g. "PRASA" vs "PUERTO RICO AQUEDUCT AND SEWER").
    Returns the higher of the two scores, capped at 1.0.
    """
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)

    try:
        from rapidfuzz import fuzz

        # token_set_ratio handles subset/superset matches well (returns 0-100)
        fuzzy = fuzz.token_set_ratio(a, b) / 100.0
    except ImportError:
        fuzzy = 0.0

    return max(jaccard, fuzzy)


def vendor_hash(name: str) -> str:
    """Stable 12-char MD5 cache key for a vendor name."""
    return hashlib.md5(normalize_vendor(name).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


class SamApiError(RuntimeError):
    """Base exception retaining SAM's failure class instead of returning ``None``."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SamQuotaExhausted(SamApiError):
    """SAM refused further calls for the current quota/rate window."""


class SamTransientError(SamApiError):
    """A transport or server failure that may succeed on a later run."""


_SAM_SESSION = _requests.Session()


def sam_call(params: dict, api_key: str, timeout: tuple = (5, 7)):
    """GET SAM.gov while preserving quota, terminal, and transient failures."""
    full_params = {"api_key": api_key, **params}
    try:
        resp = _SAM_SESSION.get(SAM_BASE_URL, params=full_params, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in {403, 429}:
            retry_after = resp.headers.get("Retry-After", "unknown")
            raise SamQuotaExhausted(
                f"SAM quota/rate limit HTTP {resp.status_code}; Retry-After={retry_after}",
                status_code=resp.status_code,
            )
        if resp.status_code >= 500:
            raise SamTransientError(
                f"SAM server error HTTP {resp.status_code}", status_code=resp.status_code
            )
        raise SamApiError(
            f"SAM request rejected with HTTP {resp.status_code}: {resp.text[:160]}",
            status_code=resp.status_code,
        )
    except _requests.RequestException as exc:
        raise SamTransientError(f"SAM transport failure: {type(exc).__name__}") from exc


def sam_lookup_by_name(vendor_name: str, api_key: str) -> tuple[dict | None, bool]:
    """
    Search SAM.gov by legal business name.
    Tries original name first, then normalized name.

    Returns ``(match, errored)``. ``match`` is a result dict with UEI/CAGE/DUNS or
    ``None`` when nothing cleared the threshold. ``errored`` is ``True`` only when
    every API attempt failed at the transport level (timeout / non-200) so the
    caller can distinguish a transient failure (retry later) from a definitive
    "not in the registry" (expected for PR/local entities).

    The registration-status filter is intentionally omitted: many PR vendors have
    lapsed (inactive/expired) registrations, and restricting to active-only was
    dropping otherwise valid UEIs. Active records are still preferred implicitly
    via name scoring.
    """
    norm = normalize_vendor(vendor_name)
    search_names = [vendor_name]
    if norm != vendor_name:
        search_names.append(norm)

    any_success = False  # at least one call returned data (a real answer, not an error)
    for search_name in search_names:
        data = None
        for retry in range(RETRY_MAX):
            try:
                data = sam_call(
                    {"legalBusinessName": search_name, "page": 0, "size": 5},
                    api_key,
                )
            except SamTransientError:
                data = None
            except (SamQuotaExhausted, SamApiError):
                raise
            if data is not None:
                break
            time.sleep(RETRY_DELAY * (retry + 1))

        if data is None:
            continue

        any_success = True
        entities = data.get("entityData", [])
        if not entities:
            continue

        best, best_score = None, 0.0
        for ent in entities:
            legal = ent.get("entityRegistration", {}).get("legalBusinessName", "")
            score = name_similarity(norm, normalize_vendor(legal))
            if score > best_score:
                best_score, best = score, ent

        if best and best_score >= MATCH_THRESHOLD:
            reg = best.get("entityRegistration", {})
            core = best.get("coreData", {})
            parent = best.get("parentEntityInfo", {})
            return {
                "uei": reg.get("ueiSAM", ""),
                "cage": reg.get("cageCode", ""),
                "duns": reg.get("dunsNumber", ""),
                "sam_name": reg.get("legalBusinessName", ""),
                "match_score": round(best_score, 3),
                "status": reg.get("registrationStatus", ""),
                "expiry": reg.get("registrationExpirationDate", ""),
                "state": core.get("physicalAddress", {}).get("stateOrProvinceCode", ""),
                "parent_uei": parent.get("ueiSAM", ""),
                "parent_name": parent.get("legalBusinessName", ""),
            }, False

    return None, (not any_success)


def usaspending_lookup(vendor_name: str) -> tuple[dict | None, bool]:
    """POST to USASpending recipient search as fallback.

    Returns ``(match, errored)`` with the same contract as
    :func:`sam_lookup_by_name`: ``errored`` is ``True`` only on a transport-level
    failure, so a transient outage is not misrecorded as a definitive no-match.
    """
    norm = normalize_vendor(vendor_name)
    payload = json.dumps(
        {
            "search_text": norm,
            "recipient_type_name": "business_types",
            "order": "desc",
            "sort": "amount",
            "limit": 5,
        }
    ).encode()
    req = urllib.request.Request(
        USAS_BASE_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status != 200:
                return None, True
            data = json.loads(resp.read().decode())
            results = data.get("results", [])
            if not results:
                return None, False
            best, best_score = None, 0.0
            for r in results:
                result_name = r.get("name") or r.get("recipient_name", "")
                score = name_similarity(norm, normalize_vendor(result_name))
                if score > best_score:
                    best_score, best = score, r
            if best and best_score >= MATCH_THRESHOLD:
                matched_name = best.get("name") or best.get("recipient_name", "")
                return {
                    "uei": best.get("uei", ""),
                    "duns": best.get("duns", ""),
                    "cage": "",
                    "sam_name": matched_name,
                    "match_score": round(best_score, 3),
                    "status": "USASPENDING",
                }, False
            return None, False
    except Exception:
        return None, True


# ---------------------------------------------------------------------------
# Local (offline) resolution — runs before the federal APIs
# ---------------------------------------------------------------------------


def cluster_key(vendor_name: str, overrides: dict[str, str]) -> str:
    """Stable 12-char cache key grouping a vendor with its alias cluster.

    Uses ``moneysweep.runtime.alias_overrides`` so curated spelling variants of
    the same entity collapse to one key — resolving any one variant (and caching
    it) then satisfies all the others, avoiding duplicate API calls in the slow
    residual step.
    """
    canonical, _matched = apply_override(vendor_name, overrides)
    return hashlib.md5(canonical.encode()).hexdigest()[:12]


# Government-marker templates for a municipio name. PR municipal payees appear
# in the source data under several forms — Spanish ("MUNICIPIO DE X",
# "MUNICIPIO AUTÓNOMO DE X"), English ("MUNICIPALITY OF X", "AUTONOMOUS
# MUNICIPALITY OF X"), and a marker-only "MUNICIPIO X". Each carries an
# unambiguous government marker, so indexing all of them stays safe against
# contractors that merely share a town name. Accents are folded by
# normalize_vendor() when the index is built.
_MUNICIPIO_FORMS = (
    "MUNICIPIO DE {n}",
    "MUNICIPIO {n}",
    "MUNICIPIO AUTONOMO DE {n}",
    "MUNICIPALITY OF {n}",
    "AUTONOMOUS MUNICIPALITY OF {n}",
)


def load_municipio_index(root: Path) -> set[str]:
    """Normalized government-marked name forms for the 78 PR municipios.

    Used to *classify* municipal-government payees, which are structurally absent
    from SAM.gov (a federal contractor registry) and would otherwise be logged as
    failures. Only government-marked forms are indexed (never the bare town name),
    so an ordinary contractor that merely shares a town's name is not misclassified.
    """
    path = root / MUNICIPIO_CROSSWALK
    index: set[str] = set()
    if not path.exists():
        return index
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            canonical = (row.get("municipality_name") or "").strip()
            forms = {tpl.format(n=canonical) for tpl in _MUNICIPIO_FORMS} if canonical else set()
            for alias in (row.get("aliases") or "").split("|"):
                marker = alias.upper()
                if "MUNICIPIO" in marker or "MUNICIPALITY" in marker:
                    forms.add(alias.strip())
            for form in forms:
                normed = normalize_vendor(form)
                if normed:
                    index.add(normed)
    return index


def local_resolve(vendor_name: str, municipio_index: set[str]) -> dict | None:
    """Offline resolution against repo-local reference data.

    Currently classifies PR municipal governments. Returns a partial result dict
    (no UEI — these entities are not in SAM by design) or ``None`` to fall through
    to the federal-API lookups. Alias-cluster deduplication is handled separately
    via :func:`cluster_key`.
    """
    if normalize_vendor(vendor_name) in municipio_index:
        return {
            "uei": "",
            "cage": "",
            "duns": "",
            "sam_name": "",
            "match_score": 1.0,
            "status": "PR_MUNICIPAL_GOV",
            "parent_uei": "",
            "parent_name": "",
            "source": "LOCAL_GOV",
            "resolution_status": STATUS_RESOLVED_LOCAL_GOV,
        }
    return None


# ---------------------------------------------------------------------------
# Checkpoint / cache helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_existing_index(index_path: Path) -> dict:
    results = {}
    if index_path.exists():
        with open(index_path) as f:
            for row in csv.DictReader(f):
                results[row["vendor_name"]] = row
    return results


# ---------------------------------------------------------------------------
# Target loading
# ---------------------------------------------------------------------------


def load_targets(root: Path) -> list[dict]:
    """
    Derive vendor targets from the master CSV.
    Aggregates by vendor_name: total obligated_amount and record count.
    Falls back to reading the master directly if vendor_targets.csv doesn't exist.
    Prefers pr_contracts_master.csv (vendor_name column); falls back to
    pr_all_awards_master.csv (recipient_name column).
    """
    targets_path = root / "data" / "staging" / "processed" / "vendor_targets.csv"
    master_path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    unified_path = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    current_master = (
        master_path if master_path.exists() else (unified_path if unified_path.exists() else None)
    )

    if targets_path.exists():
        with open(targets_path) as f:
            rows = list(csv.DictReader(f))
        # Old target caches predate direct-UEI propagation. Rebuild them when a
        # master is available so an authoritative identifier is never discarded.
        # A newly rebuilt master also invalidates the target cache so new vendors
        # and corrected award values appear in the same pipeline run.
        cache_has_uei = bool(rows) and "source_uei" in rows[0]
        cache_is_fresh = bool(
            current_master is None
            or targets_path.stat().st_mtime_ns >= current_master.stat().st_mtime_ns
        )
        if current_master is None or (cache_has_uei and cache_is_fresh):
            return [
                {
                    "vendor_name": r["vendor_name"],
                    "total_value": float(r.get("total_value", 0) or 0),
                    "record_count": int(r.get("record_count", 1) or 1),
                    "source_uei": (r.get("source_uei") or "").strip(),
                }
                for r in rows
                if r.get("vendor_name", "").strip()
            ]

    # Determine which master to use and what the name column is called
    if master_path.exists():
        read_path = master_path
        name_col = "vendor_name"
    elif unified_path.exists():
        read_path = unified_path
        name_col = "recipient_name"
    else:
        raise FileNotFoundError(
            f"No master file found. Expected one of:\n"
            f"  {master_path}\n"
            f"  {unified_path}\n"
            "Run: python3 scripts/build_unified_master.py"
        )

    # Aggregate from master
    vendor_totals: dict[str, dict] = {}
    with open(read_path) as f:
        for row in csv.DictReader(f):
            vn = row.get(name_col, "").strip()
            if not vn:
                continue
            try:
                amt = float(row.get("obligated_amount", 0) or 0)
            except (ValueError, TypeError):
                amt = 0.0
            if vn not in vendor_totals:
                vendor_totals[vn] = {
                    "total_value": 0.0,
                    "record_count": 0,
                    "uei_value": Counter(),
                }
            vendor_totals[vn]["total_value"] += amt
            vendor_totals[vn]["record_count"] += 1
            uei = (row.get("recipient_uei") or "").strip()
            if uei and uei.lower() not in {"nan", "<na>", "none"}:
                # Prefer the identifier attached to the greatest observed value.
                vendor_totals[vn]["uei_value"][uei] += max(abs(amt), 1.0)

    targets = []
    for vn, stats in vendor_totals.items():
        uei_value = stats.pop("uei_value")
        source_uei = uei_value.most_common(1)[0][0] if uei_value else ""
        targets.append({"vendor_name": vn, **stats, "source_uei": source_uei})
    targets.sort(key=lambda x: x["total_value"], reverse=True)

    # Write for reuse
    with open(targets_path, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["vendor_name", "total_value", "record_count", "source_uei"]
        )
        w.writeheader()
        w.writerows(targets)

    return targets


OFFLINE_MATCH_FILES = (
    "sam_bulk_v2_matches.csv",
    "sam_bulk_v2_confirmed_k2.csv",
)


def load_offline_matches(root: Path) -> dict[str, dict]:
    """Load authoritative monthly-extract matches under exact and normalized names."""
    output_dir = root / "data" / "staging" / "processed" / "enrichment"
    matches: dict[str, dict] = {}
    for filename in OFFLINE_MATCH_FILES:
        path = output_dir / filename
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                vendor = (row.get("vendor_name") or "").strip()
                uei = (row.get("uei") or "").strip()
                if not vendor or not uei:
                    continue
                resolved = {
                    "uei": uei,
                    "cage": row.get("cage", ""),
                    "duns": row.get("duns", ""),
                    "sam_name": row.get("sam_name", ""),
                    "match_score": row.get("match_score", 1.0),
                    "status": row.get("status", ""),
                    "expiry": row.get("expiry", ""),
                    "state": row.get("state", ""),
                    "parent_uei": row.get("parent_uei", ""),
                    "parent_name": row.get("parent_name", ""),
                    "source": row.get("source", "SAM_BULK_V2"),
                    "resolution_status": STATUS_RESOLVED_SAM_BULK,
                }
                matches.setdefault(vendor, resolved)
                matches.setdefault(normalize_vendor(vendor), resolved)
    return matches


# ---------------------------------------------------------------------------
# Index writer
# ---------------------------------------------------------------------------


def write_index(results: dict, output_dir: Path) -> None:
    fieldnames = [
        "vendor_name",
        "normalized_name",
        "total_value",
        "uei",
        "cage",
        "duns",
        "sam_name",
        "match_score",
        "status",
        "expiry",
        "state",
        "parent_uei",
        "parent_name",
        "source",
        "resolution_status",
        "resolved_at",
    ]
    index_path = output_dir / "vendor_uei_index.csv"
    with open(index_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in sorted(
            results.values(), key=lambda x: float(x.get("total_value", 0)), reverse=True
        ):
            w.writerow(r)


# ---------------------------------------------------------------------------
# Master merge
# ---------------------------------------------------------------------------


def merge_into_master(results: dict, root: Path, output_dir: Path, logger) -> None:
    """Patch master CSV with resolved UEI/CAGE/DUNS → master_enriched.csv."""
    master_path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    if not master_path.exists():
        logger.warning(f"  Master not found at {master_path} — skipping merge")
        return

    uei_map: dict[str, dict] = {}
    for vendor, row in results.items():
        if row.get("uei"):
            uei_map[vendor] = row
            uei_map[normalize_vendor(vendor)] = row

    with open(master_path) as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for col in ("recipient_uei", "recipient_cage", "recipient_duns", "parent_uei", "parent_name"):
        if col not in fieldnames:
            fieldnames.append(col)

    patched = 0
    for row in rows:
        vn = row.get("vendor_name", "").strip()
        match = uei_map.get(vn) or uei_map.get(normalize_vendor(vn))
        if match:
            changed = False
            if not row.get("recipient_uei"):
                row["recipient_uei"] = match.get("uei", "")
                changed = bool(row["recipient_uei"])
            for column, source_field in (
                ("recipient_cage", "cage"),
                ("recipient_duns", "duns"),
                ("parent_uei", "parent_uei"),
                ("parent_name", "parent_name"),
            ):
                if not row.get(column) and match.get(source_field):
                    row[column] = match[source_field]
                    changed = True
            if changed:
                patched += 1

    out_path = output_dir / "master_enriched.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    pct = patched / max(len(rows), 1) * 100
    logger.info(
        f"  Patched {patched:,}/{len(rows):,} master records ({pct:.1f}%) → {out_path.name}"
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(
    root: Path | None = None,
    resume: bool = False,
    dry_run: bool = False,
    top_n: int | None = None,
    max_api: int = 100,
    use_api: bool = False,
    circuit_breaker_failures: int = 3,
) -> dict:
    if root is None:
        root = PROJECT_ROOT

    output_dir = root / "data" / "staging" / "processed" / "enrichment"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("sam_enrichment")

    if use_api and max_api < 1:
        raise ValueError("max_api must be at least 1")
    if circuit_breaker_failures < 1:
        raise ValueError("circuit_breaker_failures must be at least 1")

    # Offline resolution is the safe default. The key is only required when a
    # caller explicitly opts into the bounded live residual pass.
    api_key = get_sam_api_key() if use_api else ""

    if dry_run:
        logger.info("[DRY RUN] Config validated.")
        logger.info(f"  SAM endpoint: {SAM_BASE_URL}")
        logger.info(f"  API residual: {'enabled' if use_api else 'disabled'}")
        if use_api:
            logger.info("  API key:      configured (value redacted)")
        logger.info(
            f"  Master path:  {root / 'data' / 'staging' / 'processed' / 'pr_contracts_master.csv'}"
        )
        logger.info(f"  Output dir:   {output_dir}")
        return {"dry_run": True}

    logger.info("[INIT] Loading targets...")
    targets = load_targets(root)
    if top_n:
        targets = targets[:top_n]
        logger.info(f"[INIT] Capped to top {top_n} vendors by value")

    logger.info(f"[INIT] {len(targets):,} unique vendors to resolve")
    total_value = sum(t["total_value"] for t in targets)
    logger.info(f"[INIT] Total contract value: ${total_value:,.0f}")

    # Repo-local reference data for offline resolution (no API cost).
    overrides = load_overrides()
    municipio_index = load_municipio_index(root)
    offline_matches = load_offline_matches(root)
    logger.info(
        f"[INIT] Local data: {len(overrides):,} alias overrides, "
        f"{len(municipio_index):,} municipio forms, "
        f"{len(offline_matches):,} bulk match keys"
    )

    cache_path = output_dir / "sam_cache.json"
    checkpoint_path = output_dir / "checkpoint.json"
    index_path = output_dir / "vendor_uei_index.csv"
    fail_path = output_dir / "failed_lookups.csv"

    cache = _load_json(cache_path)
    results = _load_existing_index(index_path) if resume else {}
    # Re-scan every vendor through the cheap offline stages on each run. Existing
    # resolved rows are skipped below; an old live-API checkpoint must never hide
    # a newly arrived source UEI or monthly bulk match.
    start_idx = 0

    # Vendors that hit a transient LOOKUP_ERROR on a prior run must be revisited
    # even though the sequential checkpoint has advanced past their index —
    # otherwise "will retry" is a lie and every pre-checkpoint transient failure
    # is lost. They are re-processed below regardless of start_idx.
    retry_errored = (
        {v for v, r in results.items() if r.get("resolution_status") == STATUS_LOOKUP_ERROR}
        if resume
        else set()
    )

    if resume and start_idx > 0:
        logger.info(f"[RESUME] Resuming from vendor #{start_idx}")
    if retry_errored:
        logger.info(f"[RESUME] Revisiting {len(retry_errored):,} prior transient errors")

    resolved = sum(1 for r in results.values() if r.get("uei"))
    failed = []
    processed = 0
    api_calls = 0
    consecutive_errors = 0
    stopped_reason = ""
    status_counts: Counter[str] = Counter()

    if use_api:
        logger.info(f"[GUARD] Daily API budget: stop after {max_api:,} live lookups")
    else:
        logger.info("[GUARD] Offline-only mode; live API residual is disabled")

    logger.info(f"[START] {datetime.now().isoformat()}")

    for i, target in enumerate(targets):
        vendor = target["vendor_name"]
        # Skip vendors already covered by the resume checkpoint, except ones we
        # still owe a retry for (prior transient errors).
        if i < start_idx and vendor not in retry_errored:
            continue
        norm = normalize_vendor(vendor)
        h = cluster_key(vendor, overrides)

        # Preserve identifiers already carried by the award source before any
        # fuzzy name search. These are authoritative and cost no API calls.
        source_uei = (target.get("source_uei") or "").strip()
        if source_uei:
            existing = results.get(vendor, {})
            cached = cache.get(h, {})
            was_resolved = bool(existing.get("uei"))
            direct = {
                "uei": source_uei,
                "cage": "",
                "duns": "",
                "sam_name": vendor,
                "match_score": 1.0,
                "status": "SOURCE_RECORD",
                "expiry": "",
                "state": "",
                "parent_uei": "",
                "parent_name": "",
                "source": "SOURCE_UEI",
                "resolution_status": STATUS_RESOLVED_SOURCE_UEI,
            }
            # Keep richer metadata from a prior SAM/bulk resolution for the same
            # authoritative UEI. Source propagation must not erase a known
            # parent, CAGE, DUNS, or legal name.
            for field in (
                "cage",
                "duns",
                "sam_name",
                "expiry",
                "state",
                "parent_uei",
                "parent_name",
            ):
                for prior in (existing, cached):
                    if prior.get("uei") == source_uei and prior.get(field):
                        direct[field] = prior[field]
                        break
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "resolved_at": datetime.now().isoformat(),
                **direct,
            }
            cache[h] = direct
            if not was_resolved:
                resolved += 1
            status_counts[STATUS_RESOLVED_SOURCE_UEI] += 1
            processed += 1
            continue

        # Monthly SAM public extract matches are the next authoritative layer.
        bulk = offline_matches.get(vendor) or offline_matches.get(norm)
        if bulk:
            was_resolved = bool(results.get(vendor, {}).get("uei"))
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "resolved_at": datetime.now().isoformat(),
                **bulk,
            }
            cache[h] = bulk
            if not was_resolved:
                resolved += 1
            status_counts[STATUS_RESOLVED_SAM_BULK] += 1
            processed += 1
            continue

        if vendor in results and results[vendor].get("uei"):
            status_counts[results[vendor].get("resolution_status", STATUS_RESOLVED_SAM)] += 1
            processed += 1
            continue

        # Cache hit (shared across an alias cluster via cluster_key)
        if h in cache:
            hit = cache[h]
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                **hit,
                "source": "cache",
                "resolved_at": datetime.now().isoformat(),
            }
            if hit.get("uei"):
                resolved += 1
            status_counts[hit.get("resolution_status", STATUS_RESOLVED_SAM)] += 1
            processed += 1
            continue

        # Local (offline) resolution — no API cost. Classifies PR municipal
        # governments, which are structurally absent from SAM.gov, instead of
        # burning an API call and logging them as failures.
        local = local_resolve(vendor, municipio_index)
        if local is not None:
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "resolved_at": datetime.now().isoformat(),
                **local,
            }
            cache[h] = local
            status_counts[local["resolution_status"]] += 1
            logger.info(
                f"  [{i + 1}/{len(targets)}] {vendor[:50]} "
                f"— {local['resolution_status'].lower()} (PR government; not in SAM)"
            )
            processed += 1
            continue

        if not use_api:
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "uei": "",
                "cage": "",
                "duns": "",
                "sam_name": "",
                "match_score": 0,
                "status": "DEFERRED",
                "expiry": "",
                "state": "",
                "parent_uei": "",
                "parent_name": "",
                "source": "NONE",
                "resolution_status": STATUS_DEFERRED_API,
                "resolved_at": datetime.now().isoformat(),
            }
            status_counts[STATUS_DEFERRED_API] += 1
            processed += 1
            if processed % 1000 == 0:
                logger.info(f"  [OFFLINE] Classified {processed:,}/{len(targets):,} vendors")
            continue

        # Daily API budget guard — checkpoint and stop before exceeding the cap
        if max_api and api_calls >= max_api:
            stopped_reason = "api_budget"
            _save_json(
                checkpoint_path,
                {"last_idx": i, "resolved": resolved, "ts": datetime.now().isoformat()},
            )
            write_index(results, output_dir)
            _save_json(cache_path, cache)
            logger.info(
                f"[GUARD] Reached API budget ({max_api:,} lookups) at vendor #{i}. "
                f"Checkpoint saved — rerun with --resume tomorrow."
            )
            break

        # SAM primary lookup
        time.sleep(RATE_DELAY)
        try:
            sam_result, sam_errored = sam_lookup_by_name(vendor, api_key)
        except SamQuotaExhausted as exc:
            stopped_reason = "sam_quota_or_rate_limit"
            logger.warning(f"[CIRCUIT] {exc}; checkpointing immediately")
            break
        except SamApiError as exc:
            stopped_reason = f"sam_rejected_http_{exc.status_code or 'unknown'}"
            logger.error(f"[CIRCUIT] {exc}; checkpointing immediately")
            break
        api_calls += 1
        source = "SAM"
        usas_errored = False

        # USASpending fallback
        if not sam_result or not sam_result.get("uei"):
            usas_result, usas_errored = usaspending_lookup(vendor)
            if usas_result and usas_result.get("uei"):
                sam_result = usas_result
                source = "USASPENDING"

        if sam_result and sam_result.get("uei"):
            resolution_status = STATUS_RESOLVED_SAM if source == "SAM" else STATUS_RESOLVED_USAS
            row = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "source": source,
                "resolution_status": resolution_status,
                "resolved_at": datetime.now().isoformat(),
                **sam_result,
            }
            results[vendor] = row
            cache[h] = {**sam_result, "resolution_status": resolution_status}
            resolved += 1
            consecutive_errors = 0
            status_counts[resolution_status] += 1
            logger.info(
                f"  [{i + 1}/{len(targets)}] {vendor[:50]}\n"
                f"       UEI={sam_result['uei']} CAGE={sam_result.get('cage', '')} "
                f"score={sam_result.get('match_score', '')}"
            )
        else:
            # A transient failure (both lookups errored at the transport level) is
            # NOT a definitive miss: leave it uncached and un-failed so it retries
            # on the next --resume, rather than being stamped as unresolved forever.
            transient = sam_errored and usas_errored
            resolution_status = STATUS_LOOKUP_ERROR if transient else STATUS_NO_FEDERAL_MATCH
            results[vendor] = {
                "vendor_name": vendor,
                "normalized_name": norm,
                "total_value": target["total_value"],
                "uei": "",
                "cage": "",
                "duns": "",
                "sam_name": "",
                "match_score": 0,
                "status": "ERROR" if transient else "UNRESOLVED",
                "parent_uei": "",
                "parent_name": "",
                "source": "NONE",
                "resolution_status": resolution_status,
                "resolved_at": datetime.now().isoformat(),
            }
            status_counts[resolution_status] += 1
            if transient:
                consecutive_errors += 1
                logger.warning(
                    f"  [{i + 1}/{len(targets)}] {vendor[:50]} — lookup error "
                    f"({consecutive_errors}/{circuit_breaker_failures})"
                )
                if consecutive_errors >= circuit_breaker_failures:
                    stopped_reason = "transport_circuit_open"
                    logger.warning(
                        "[CIRCUIT] Sustained SAM/USASpending outage; "
                        "checkpointing instead of retrying every vendor"
                    )
            else:
                consecutive_errors = 0
                failed.append(vendor)
                cache[h] = {
                    **results[vendor],
                    "resolution_status": STATUS_NO_FEDERAL_MATCH,
                }
                logger.info(
                    f"  [{i + 1}/{len(targets)}] {vendor[:50]} "
                    f"— no federal-registry match (expected for PR/local entities)"
                )

        processed += 1

        if processed % BATCH_SIZE == 0:
            write_index(results, output_dir)
            _save_json(cache_path, cache)
            _save_json(
                checkpoint_path,
                {
                    "last_idx": i + 1,
                    "resolved": resolved,
                    "ts": datetime.now().isoformat(),
                },
            )
            coverage = resolved / max(processed, 1)
            logger.info(
                f"  [CHECKPOINT] {resolved}/{processed} resolved ({coverage:.1%}) | "
                f"${sum(float(r.get('total_value', 0)) for r in results.values() if r.get('uei')):,.0f} covered"
            )

        if stopped_reason == "transport_circuit_open":
            break

    # Final write
    write_index(results, output_dir)
    _save_json(cache_path, cache)
    _save_json(
        checkpoint_path,
        {
            "last_idx": processed,
            "resolved": resolved,
            "api_calls": api_calls,
            "stopped_reason": stopped_reason,
            "ts": datetime.now().isoformat(),
        },
    )

    target_results = [results.get(t["vendor_name"], {}) for t in targets]
    failed = [
        t["vendor_name"]
        for t in targets
        if results.get(t["vendor_name"], {}).get("resolution_status") == STATUS_NO_FEDERAL_MATCH
    ]
    with open(fail_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["vendor_name"])
        writer.writerows([[vendor] for vendor in failed])

    merge_into_master(results, root, output_dir, logger)

    # Report against the full requested target universe, not merely the prefix
    # reached before an API budget/circuit stop.
    total_processed = len(targets)
    resolved = sum(1 for result in target_results if result.get("uei"))
    deferred = sum(
        1
        for result in target_results
        if result.get("resolution_status") in {STATUS_DEFERRED_API, STATUS_LOOKUP_ERROR}
    )
    coverage = resolved / max(total_processed, 1)
    value_resolved = sum(
        float(result.get("total_value", 0)) for result in target_results if result.get("uei")
    )
    value_total = sum(t["total_value"] for t in targets)
    status_counts = Counter(
        result.get("resolution_status", STATUS_DEFERRED_API) for result in target_results
    )

    summary = {
        "run_ts": datetime.now().isoformat(),
        "vendors_attempted": total_processed,
        "vendors_resolved": resolved,
        "vendors_failed": len(failed),
        "vendors_deferred": deferred,
        "api_enabled": use_api,
        "api_calls": api_calls,
        "stopped_reason": stopped_reason,
        "coverage_pct": round(coverage * 100, 2),
        "value_resolved_usd": round(value_resolved, 2),
        "value_total_usd": round(value_total, 2),
        "value_coverage_pct": round(value_resolved / max(value_total, 1) * 100, 2),
        "coverage_gate_pass": coverage >= COVERAGE_GATE,
        "status_breakdown": dict(status_counts),
    }
    _save_json(output_dir / "enrichment_summary.json", summary)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"[COMPLETE] {datetime.now().isoformat()}")
    logger.info(f"  Resolved:      {resolved:,} / {total_processed:,} ({coverage:.1%})")
    logger.info(f"  Deferred API:  {deferred:,}")
    logger.info(
        f"  Value covered: ${value_resolved:,.0f} / ${value_total:,.0f} ({summary['value_coverage_pct']:.1f}%)"
    )
    if status_counts:
        breakdown = ", ".join(f"{k}={v:,}" for k, v in status_counts.most_common())
        logger.info(f"  Breakdown:     {breakdown}")
    if summary["coverage_gate_pass"]:
        gate_text = "PASS"
    elif use_api:
        gate_text = "FAIL — see failed_lookups.csv"
    else:
        gate_text = "DEFERRED — offline pass complete; API residual not requested"
    logger.info(f"  Gate:          {gate_text}")

    if not summary["coverage_gate_pass"] and use_api:
        logger.warning(
            f"  Coverage {coverage:.1%} below gate ({COVERAGE_GATE:.0%}). "
            f"Check {fail_path} for manual resolution."
        )

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAM.gov UEI batch enrichment")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--dry-run", action="store_true", help="Validate config only, no API calls")
    parser.add_argument("--top", type=int, metavar="N", help="Only enrich top N vendors by value")
    parser.add_argument(
        "--use-api",
        action="store_true",
        help="Enable the live SAM/USASpending residual pass (offline-only by default)",
    )
    parser.add_argument(
        "--max-api",
        type=int,
        metavar="N",
        dest="max_api",
        default=100,
        help="Stop after N live API lookups (default: 100; requires --use-api)",
    )
    parser.add_argument(
        "--circuit-breaker-failures",
        type=int,
        default=3,
        help="Stop after this many consecutive transport failures (default: 3)",
    )
    args = parser.parse_args()

    summary = run(
        resume=args.resume,
        dry_run=args.dry_run,
        top_n=args.top,
        max_api=args.max_api,
        use_api=args.use_api,
        circuit_breaker_failures=args.circuit_breaker_failures,
    )
    sys.exit(
        0 if summary.get("dry_run") or not args.use_api or summary.get("coverage_gate_pass") else 1
    )
