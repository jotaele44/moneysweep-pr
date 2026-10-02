"""Fail-closed ingestion helpers for the frozen MII v0.3 reference.

MII evidence classes are preserved as source metadata. They are never translated
into MoneySweep binding evidence, and source manifestations are never promoted to
canonical entities by this module.
"""

from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PDF_NAME = "PR ecosystem network · MII v0.3.pdf"
ZIP_NAME = "PR ecosystem network · MII v0.3.zip"
PDF_SHA256 = "4e99ddb6efa80ef36909429f27a315064367c57449ad1e4f9dcc301d802925b3"
ZIP_SHA256 = "cd55c56785d5e8258f4cc5b9d5a5dcb8541c7e183e33a49f6a60430ecb34725d"
PDF_PAGE_COUNT = 10
REFERENCE_DIR = Path("data/reference/entity_network/mii_v0_3")

BOARD_BY_PAGE = {
    2: "PHARMA_BIOTECH_MEDDEV",
    3: "AEROSPACE_DEFENSE",
    4: "ENERGY_FUELS_GRID",
    5: "TRANSPORT_LOGISTICS",
    6: "TELECOM_CONNECTIVITY",
    7: "GOVERNANCE_PUBLIC_FINANCE_OVERSIGHT",
    8: "RESEARCH_ACADEMIA_WORKFORCE",
}
PRIMARY_SECTOR_BY_CODE = {
    "PH": "PHARMA_BIOTECH_MEDDEV",
    "AD": "AEROSPACE_DEFENSE",
    "EN": "ENERGY_FUELS_GRID",
    "WA": "WATER_WASTEWATER_ENVIRONMENT",
    "TR": "TRANSPORT_LOGISTICS",
    "TC": "TELECOM_CONNECTIVITY",
    "IN": "INDUSTRIAL_MANUFACTURING_EPC_CONSTRUCTION",
    "GV": "GOVERNANCE_PUBLIC_FINANCE_OVERSIGHT",
    "RS": "RESEARCH_ACADEMIA_WORKFORCE",
}
MII_CODES = frozenset(PRIMARY_SECTOR_BY_CODE)
EVIDENCE_CLASSES = frozenset({"A", "B", "C"})
COLUMN_X0 = (50.25, 260.25, 470.25, 680.25, 890.25)

ZIP_MEMBER_EXPECTATIONS = {
    "Main.dc.html": (
        14586,
        "4f01835616f5ef6e30162e34db7f6f80c9d6b858dee4caeb28905b1398dbfdf8",
    ),
    "ds/pr-int/styles.css": (
        42930,
        "17bc93d6aa29a0805173701462ab287032dfaa67886c25521e807aff6ba5206c",
    ),
    "support.js": (
        45305,
        "ffb137b73e1813ce75a89cf24be37226c926cc18bbba287fcbd7758927e240fb",
    ),
    "vendor/react.js": (
        10751,
        "d949f1c3687aedadcedac85261865f29b17cd273997e7f6b2bfc53b2f9d4c4dd",
    ),
    "vendor/react-dom.js": (
        131835,
        "35f4f974f4b2bcd44da73963347f8952e341f83909e4498227d4e26b98f66f0d",
    ),
    "README.md": (
        937,
        "1a9015dc8eed09db5063703a3db33e54e7c39518d4f3a4cf4b06c6c96633db6f",
    ),
}


class MIIReferenceError(ValueError):
    """Raised when a frozen-source or reconciliation invariant fails."""


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}{hashlib.sha256(raw).hexdigest()[:20]}"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def mii_evidence_is_binding(evidence_class: str) -> bool:
    """MII A/B/C are source-local classes and never MoneySweep identity bindings."""
    if evidence_class not in EVIDENCE_CLASSES:
        raise MIIReferenceError(f"unknown MII evidence class: {evidence_class}")
    return False


def validate_reference_bundle(reference_dir: Path) -> dict[str, Any]:
    """Validate committed aggregate MII reference artifacts without source bytes."""
    manifest = _load_json(reference_dir / "source_manifest.json")
    coverage = _load_json(reference_dir / "coverage_ledger.json")
    exhaustion = _load_json(reference_dir / "exhaustion_ledger.json")
    contradictions = _load_json(reference_dir / "contradictions.json")
    reconciliation = _load_json(reference_dir / "reconciliation.json")
    bindings = _load_json(reference_dir / "source_bindings.json")

    artifacts = {item["name"]: item for item in manifest["artifacts"]}
    if artifacts[PDF_NAME]["sha256"] != PDF_SHA256:
        raise MIIReferenceError("committed PDF hash does not match frozen MII v0.3")
    if artifacts[ZIP_NAME]["sha256"] != ZIP_SHA256:
        raise MIIReferenceError("committed ZIP hash does not match frozen MII v0.3")
    if artifacts[PDF_NAME]["page_count"] != PDF_PAGE_COUNT:
        raise MIIReferenceError("unexpected frozen PDF page count")

    sectors = coverage["sectors"]
    if len(sectors) != 10:
        raise MIIReferenceError("coverage ledger must contain exactly 10 MII sectors")
    if len({row["sector_id"] for row in sectors}) != 10:
        raise MIIReferenceError("coverage ledger sector IDs are not unique")
    if sum(row["declared_curated_nodes"] for row in sectors) != 223:
        raise MIIReferenceError("declared curated-node arithmetic does not close to 223")
    if sum(row["declared_board_edges"] for row in sectors) != 272:
        raise MIIReferenceError("ecosystem board-edge arithmetic does not close to 272")

    node = reconciliation["node_arithmetic"]
    if (
        node["distinct_visible_card_signatures"]
        + node["unmaterialized_declared_node_residue"]
        != 223
    ):
        raise MIIReferenceError("visible-node + residue arithmetic does not close")
    edge = reconciliation["edge_arithmetic"]
    if (
        edge["internal_edges_computed"] + 2 * edge["cross_ecosystem_edges"]
        != edge["sum_ecosystem_board_edges"]
    ):
        raise MIIReferenceError("cross-ecosystem edge arithmetic does not close")
    if edge["row_level_edge_ingest_state"] != "BLOCKED_SOURCE_ARTIFACT_NOT_EXPOSED":
        raise MIIReferenceError("row-level edge ingest must remain blocked")

    source_ids = {
        row["contradiction_id"] for row in contradictions["source_contradictions"]
    }
    if source_ids != {f"V3C-00{index}" for index in range(1, 7)}:
        raise MIIReferenceError(
            "source contradiction denominator must be V3C-001..V3C-006"
        )
    if len(exhaustion["vectors"]) != 10:
        raise MIIReferenceError("exhaustion ledger must contain exactly 10 source vectors")
    if len(bindings["bindings"]) != 10:
        raise MIIReferenceError("source binding ledger must contain exactly 10 vectors")

    boundaries = manifest["identity_boundaries"]
    if any(boundaries.values()):
        raise MIIReferenceError("identity boundary flags must remain fail-closed")

    return {
        "status": "PASS",
        "sector_count": len(sectors),
        "source_vector_count": len(exhaustion["vectors"]),
        "source_contradiction_count": len(source_ids),
        "ingest_contradiction_count": len(
            contradictions["ingest_contradictions"]
        ),
        "row_level_edge_state": edge["row_level_edge_ingest_state"],
    }


def verify_source_artifacts(pdf_path: Path, zip_path: Path) -> dict[str, Any]:
    """Verify exact source bytes and ZIP member payloads before extraction."""
    if sha256_path(pdf_path) != PDF_SHA256:
        raise MIIReferenceError("PDF SHA-256 mismatch")
    if sha256_path(zip_path) != ZIP_SHA256:
        raise MIIReferenceError("ZIP SHA-256 mismatch")

    with zipfile.ZipFile(zip_path) as archive:
        observed = {}
        members = []
        for info in archive.infolist():
            payload = archive.read(info.filename)
            digest = hashlib.sha256(payload).hexdigest()
            observed[info.filename] = (info.file_size, digest)
            members.append(
                {
                    "path": info.filename,
                    "uncompressed_size": info.file_size,
                    "sha256": digest,
                }
            )
    if observed != ZIP_MEMBER_EXPECTATIONS:
        raise MIIReferenceError("ZIP member payload inventory mismatch")
    return {
        "pdf_sha256": PDF_SHA256,
        "zip_sha256": ZIP_SHA256,
        "zip_members": members,
    }


def _page_lines(page: Any) -> dict[float, list[dict[str, Any]]]:
    lines: defaultdict[float, list[dict[str, Any]]] = defaultdict(list)
    for word in page.extract_words(
        x_tolerance=1,
        y_tolerance=2,
        keep_blank_chars=False,
        use_text_flow=False,
    ):
        lines[round(float(word["top"]), 1)].append(word)
    return {
        top: sorted(words, key=lambda item: item["x0"])
        for top, words in lines.items()
    }


def _words_in_column(
    words: list[dict[str, Any]],
    left: float,
    right: float,
) -> list[dict[str, Any]]:
    return [word for word in words if left - 1 <= word["x0"] < right - 1]


def extract_visible_node_cards(pdf_path: Path) -> list[dict[str, Any]]:
    """Extract rendered node-card manifestations from ecosystem pages 2..8."""
    import pdfplumber

    cards: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as document:
        if len(document.pages) != PDF_PAGE_COUNT:
            raise MIIReferenceError(
                "unexpected PDF page count during node extraction"
            )
        for page_number, board_sector in BOARD_BY_PAGE.items():
            page = document.pages[page_number - 1]
            lines = _page_lines(page)
            tops = sorted(lines)
            for top in tops:
                for column_index, left in enumerate(COLUMN_X0):
                    right = (
                        COLUMN_X0[column_index + 1]
                        if column_index + 1 < len(COLUMN_X0)
                        else float(page.width) + 1
                    )
                    words = _words_in_column(lines[top], left, right)
                    tokens = [word["text"] for word in words]
                    if not (
                        len(tokens) >= 5
                        and tokens[0] in MII_CODES
                        and tokens[1] == "·"
                        and tokens[2] in EVIDENCE_CLASSES
                        and tokens[3] == "·"
                    ):
                        continue

                    candidates: list[tuple[float, float, str]] = []
                    for previous_top in tops:
                        if previous_top >= top:
                            break
                        gap = top - previous_top
                        if not 5 < gap < 25:
                            continue
                        previous_words = _words_in_column(
                            lines[previous_top],
                            left,
                            right,
                        )
                        if previous_words:
                            candidates.append(
                                (
                                    gap,
                                    previous_top,
                                    " ".join(
                                        word["text"] for word in previous_words
                                    ),
                                )
                            )
                    if not candidates:
                        raise MIIReferenceError(
                            "node card has no preceding name: "
                            f"page={page_number} top={top}"
                        )
                    _, name_top, raw_name = min(candidates)
                    raw_location = None
                    if len(tokens) > 6 and tokens[5] == "·":
                        raw_location = " ".join(tokens[6:])
                    payload = {
                        "page": page_number,
                        "board_sector": board_sector,
                        "column": column_index + 1,
                        "name_top": name_top,
                        "meta_top": top,
                        "raw_name": raw_name,
                        "ecosystem_code": tokens[0],
                        "primary_sector": PRIMARY_SECTOR_BY_CODE[tokens[0]],
                        "evidence_class": tokens[2],
                        "raw_type": tokens[4],
                        "raw_location": raw_location,
                    }
                    cards.append(
                        {
                            "manifestation_id": _stable_id(
                                "mii_v03_card_",
                                payload,
                            ),
                            **payload,
                            "identity_state": "UNRESOLVED",
                            "canonical_entity_id": None,
                            "source_artifact": PDF_NAME,
                            "source_sha256": PDF_SHA256,
                        }
                    )
    return sorted(
        cards,
        key=lambda row: (row["page"], row["meta_top"], row["column"]),
    )


def extract_visible_registry_candidates(
    pdf_path: Path,
) -> list[dict[str, Any]]:
    """Extract page-9 name-only candidates without promoting them to identity."""
    import pdfplumber

    candidates: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as document:
        page = document.pages[8]
        lines = _page_lines(page)
        tops = sorted(lines)
        halves = (
            (0.0, 530.0, "WATER"),
            (530.0, 1063.0, "INDUSTRIAL"),
        )
        for top in tops:
            for left, right, sector in halves:
                words = [
                    word for word in lines[top] if left <= word["x0"] < right
                ]
                tokens = [word["text"] for word in words]
                if not {
                    "registry",
                    "name-only",
                    "candidate",
                }.issubset(tokens):
                    continue
                prior: list[tuple[float, float, str]] = []
                for previous_top in tops:
                    if previous_top >= top:
                        break
                    gap = top - previous_top
                    if gap >= 20:
                        continue
                    previous_words = [
                        word
                        for word in lines[previous_top]
                        if left <= word["x0"] < right
                    ]
                    if previous_words:
                        prior.append(
                            (
                                gap,
                                previous_top,
                                " ".join(
                                    word["text"] for word in previous_words
                                ),
                            )
                        )
                amount_text = None
                amount_top = None
                raw_name = None
                name_top = None
                for _, previous_top, text in sorted(prior):
                    if text.startswith("$") and amount_text is None:
                        amount_text = text
                        amount_top = previous_top
                    elif not text.startswith("$") and raw_name is None:
                        raw_name = text
                        name_top = previous_top
                if raw_name is None:
                    raise MIIReferenceError(
                        "registry candidate missing raw name"
                    )
                payload = {
                    "page": 9,
                    "sector": sector,
                    "name_top": name_top,
                    "amount_top": amount_top,
                    "meta_top": top,
                    "raw_name": raw_name,
                    "raw_type": tokens[0],
                    "amount_text": amount_text,
                }
                candidates.append(
                    {
                        "candidate_id": _stable_id(
                            "mii_v03_registry_",
                            payload,
                        ),
                        **payload,
                        "evidence_basis": "NAME_ONLY",
                        "identity_state": "CANDIDATE_NOT_IDENTITY",
                        "canonical_entity_id": None,
                        "source_artifact": PDF_NAME,
                        "source_sha256": PDF_SHA256,
                    }
                )
    return sorted(
        candidates,
        key=lambda row: (row["meta_top"], row["sector"]),
    )


def visible_card_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    """Source-card signature for reconciliation only, never entity identity."""
    return (
        row["raw_name"],
        row["ecosystem_code"],
        row["evidence_class"],
        row["raw_type"],
        row["raw_location"],
    )


def assert_observed_source_counts(
    cards: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, int]:
    """Gate extraction against the frozen run without synthesizing missing rows."""
    unique_signatures = {visible_card_signature(row) for row in cards}
    if len(cards) != 256:
        raise MIIReferenceError(
            "expected 256 rendered card manifestations, "
            f"got {len(cards)}"
        )
    if len(unique_signatures) != 182:
        raise MIIReferenceError(
            "expected 182 distinct visible card signatures, "
            f"got {len(unique_signatures)}"
        )
    if len(candidates) != 28:
        raise MIIReferenceError(
            f"expected 28 visible registry candidates, got {len(candidates)}"
        )
    if any(
        row["identity_state"] != "CANDIDATE_NOT_IDENTITY"
        for row in candidates
    ):
        raise MIIReferenceError(
            "registry candidate identity state was promoted"
        )

    by_code = Counter(signature[1] for signature in unique_signatures)
    expected = {
        "PH": 42,
        "AD": 34,
        "EN": 33,
        "WA": 3,
        "TR": 16,
        "TC": 17,
        "IN": 2,
        "GV": 16,
        "RS": 19,
    }
    if dict(by_code) != expected:
        raise MIIReferenceError(
            f"visible card code counts changed: {dict(by_code)}"
        )
    return {
        "rendered_card_manifestations": len(cards),
        "distinct_visible_card_signatures": len(unique_signatures),
        "visible_registry_name_only_candidates": len(candidates),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise MIIReferenceError(
            f"refusing to write empty extraction: {path.name}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def materialize_provisional_snapshot(
    pdf_path: Path,
    zip_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Verify sources, extract visible rows, and write a noncanonical snapshot."""
    verify_source_artifacts(pdf_path, zip_path)
    cards = extract_visible_node_cards(pdf_path)
    candidates = extract_visible_registry_candidates(pdf_path)
    counts = assert_observed_source_counts(cards, candidates)

    cards_path = output_dir / "visible_node_cards.csv"
    candidates_path = output_dir / "visible_registry_candidates.csv"
    _write_csv(cards_path, cards)
    _write_csv(candidates_path, candidates)

    receipt = {
        "schema_version": "mii_v0_3_provisional_materialization_receipt_v1",
        "status": "PASS",
        "canonical_promotion": False,
        "row_level_edge_state": "BLOCKED_SOURCE_ARTIFACT_NOT_EXPOSED",
        "counts": counts,
        "artifacts": {
            "visible_node_cards.csv": {
                "sha256": sha256_path(cards_path),
                "rows": len(cards),
            },
            "visible_registry_candidates.csv": {
                "sha256": sha256_path(candidates_path),
                "rows": len(candidates),
            },
        },
    }
    receipt_path = output_dir / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            receipt,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt
