"""Tests for contract_sweeper.runtime.alias_overrides and its wires."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from textwrap import dedent

import pytest

from contract_sweeper.runtime.alias_overrides import (
    AliasOverrideError,
    apply,
    load_overrides,
)


@pytest.fixture
def override_file(tmp_path: Path) -> Path:
    path = tmp_path / "alias_overrides.yaml"
    path.write_text(
        dedent(
            """
            version: "1.0"
            entries:
              - canonical_name: "LPC & D"
                aliases:
                  - "LPC and D"
                  - "LPC Contractors, Inc."
                evidence: "test"
              - canonical_name: "Autopistas de Puerto Rico"
                aliases:
                  - "Autopistas de PR LLC"
                evidence: "test"
            """
        ).strip(),
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
def test_load_overrides_returns_normalized_mapping(override_file: Path) -> None:
    mapping = load_overrides(override_file)
    # Canonical points to itself.
    assert mapping["LPC AND D"] == "LPC AND D"
    # Variant collapses to canonical normalized form.
    assert mapping["LPC CONTRACTORS"] == "LPC AND D"
    assert mapping["AUTOPISTAS DE PR"] == "AUTOPISTAS DE PUERTO RICO"


@pytest.mark.unit
def test_load_overrides_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_overrides(tmp_path / "does_not_exist.yaml") == {}


@pytest.mark.unit
def test_load_overrides_rejects_conflicting_aliases(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        dedent(
            """
            entries:
              - canonical_name: "Alpha Corp"
                aliases: ["Shared Name"]
                evidence: "x"
              - canonical_name: "Beta Corp"
                aliases: ["Shared Name"]
                evidence: "x"
            """
        ).strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasOverrideError):
        load_overrides(path)


@pytest.mark.unit
def test_load_overrides_rejects_missing_canonical(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        dedent(
            """
            entries:
              - aliases: ["something"]
                evidence: "x"
            """
        ).strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasOverrideError):
        load_overrides(path)


@pytest.mark.unit
def test_apply_collapses_known_alias(override_file: Path) -> None:
    overrides = load_overrides(override_file)
    canonical, overridden = apply("LPC Contractors, Inc.", overrides)
    assert canonical == "LPC AND D"
    assert overridden is True


@pytest.mark.unit
def test_apply_passthrough_for_unknown_name(override_file: Path) -> None:
    overrides = load_overrides(override_file)
    canonical, overridden = apply("Brown & Sons Inc", overrides)
    assert canonical == "BROWN AND SONS"
    assert overridden is False


@pytest.mark.unit
def test_apply_empty_input(override_file: Path) -> None:
    overrides = load_overrides(override_file)
    canonical, overridden = apply("", overrides)
    assert canonical == ""
    assert overridden is False


@pytest.mark.unit
def test_repo_default_overrides_loadable() -> None:
    """The shipped registries/alias_overrides.yaml must always load cleanly."""
    mapping = load_overrides()
    assert mapping, "shipped override registry should not be empty"
    # Sanity-check one seeded entry from the shipped file.
    assert "SUPERASPHALT" in mapping or "SUPERASPHALT PAVEMENT" in mapping


@pytest.fixture
def alias_repo_with_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repo where the alias builder should collapse two variants via override."""
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    rows = [
        {"award_id": "A1", "recipient_name": "LPC & D", "obligated_amount": "100000"},
        {"award_id": "A2", "recipient_name": "LPC Contractors, Inc.", "obligated_amount": "250000"},
        {"award_id": "A3", "recipient_name": "Brown & Sons Inc", "obligated_amount": "50000"},
    ]
    path = processed / "sample_contracts.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return tmp_path


@pytest.mark.integration
def test_alias_registry_builder_uses_overrides(alias_repo_with_override: Path) -> None:
    """End-to-end: builder should merge LPC variants into one cluster."""
    from scripts.alias_registry_builder import build_alias_registry

    result = build_alias_registry(alias_repo_with_override)
    entries_by_norm = {e["normalized_name"]: e for e in result["entries"]}
    # Both LPC variants collapse to the canonical LPC AND D cluster.
    assert "LPC AND D" in entries_by_norm
    lpc = entries_by_norm["LPC AND D"]
    assert lpc["row_count"] == 2
    assert lpc["override_hits"] >= 1
    assert lpc["status"] == "operator_curated_cluster"
    # Manual review is NOT required when the cluster is operator-curated.
    assert lpc["manual_review_required"] is False
    # Brown & Sons is untouched.
    assert "BROWN AND SONS" in entries_by_norm
    # One row used the canonical name itself (no override needed); the other
    # row's variant collapsed into the canonical cluster (one override).
    assert result["override_count"] >= 1


@pytest.mark.integration
def test_parent_collapse_records_override_method(alias_repo_with_override: Path) -> None:
    from scripts.parent_collapse import build_entities

    summary = build_entities(alias_repo_with_override)
    assert summary["entity_count"] >= 2
    entities_csv = (
        alias_repo_with_override / "data" / "staging" / "processed" / "entities_resolved.csv"
    )
    rows = list(csv.DictReader(entities_csv.open(encoding="utf-8")))
    lpc_rows = [r for r in rows if r["normalized_name"] == "LPC AND D"]
    assert lpc_rows, "expected LPC AND D entity after override collapse"
    assert lpc_rows[0]["resolution_method"] == "alias_override"


# ---------------------------------------------------------------------------
# Regression: shipped registry collapses ACT 2020 entity families
#
# These tests pin the behaviour of registries/alias_overrides.yaml (the
# shipped file, not a synthetic fixture) so future edits don't accidentally
# break the ACT 2020 transition PDF coverage added 2026-05-27.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_shipped_overrides_collapse_lpc_dotted_variants() -> None:
    mapping = load_overrides()  # default path → registries/alias_overrides.yaml
    canonical, overridden = apply("L. P. C. and D. Inc.", mapping)
    assert canonical == "LPC AND D"
    assert overridden is True
    # Existing form still resolves to the same canonical.
    canonical2, _ = apply("LPC Contractors, Inc.", mapping)
    assert canonical2 == "LPC AND D"


@pytest.mark.unit
def test_shipped_overrides_collapse_ferrovial_family() -> None:
    mapping = load_overrides()
    variants = [
        "FERROVIAL AGROMAN, LLC",
        "FERROVIAL- AGROMAN, SA",
        "Ferrovial Agroman, S.A.",
        "Ferrovial Agroman",
    ]
    canonicals = {apply(v, mapping)[0] for v in variants}
    assert canonicals == {"FERROVIAL AGROMAN"}
    # Sister entity stays distinct.
    sister, _ = apply("FERROVIAL CONSTRUCCION PR, LLC", mapping)
    assert sister == "FERROVIAL CONSTRUCCION PR"


@pytest.mark.unit
def test_shipped_overrides_collapse_cma_architecs_typo() -> None:
    """The typo 'Architecs' (missing T) must collapse into CMA Architects."""
    mapping = load_overrides()
    canonical, overridden = apply("CMA Architecs & Engineers, L.L.P.", mapping)
    assert canonical == "CMA ARCHITECTS AND ENGINEERS"
    assert overridden is True
    canonical2, _ = apply("CMA ARCHITECTS AND ENGINEERS LLC", mapping)
    assert canonical2 == "CMA ARCHITECTS AND ENGINEERS"


@pytest.mark.unit
def test_shipped_overrides_collapse_barrett_hale_alamo_typo() -> None:
    """'Barret' (single T typo) must collapse with 'Barrett'."""
    mapping = load_overrides()
    canonical_typo, overridden = apply("Barret Hale & Alamo, LLC", mapping)
    canonical_ok, _ = apply("Barrett, Hale & Alamo, LLC", mapping)
    assert canonical_typo == canonical_ok == "BARRETT HALE AND ALAMO"
    assert overridden is True


@pytest.mark.unit
def test_shipped_overrides_collapse_desarrolladora_ja_variants() -> None:
    mapping = load_overrides()
    variants = [
        "DESARROLLADORA J.A., INC.",
        "Desarrolladora J.A.. Inc.",
        "Desarrolladora JA, Inc..",
        "Desarrolladora J.A.",
    ]
    canonicals = {apply(v, mapping)[0] for v in variants}
    assert canonicals == {"DESARROLLADORA JA"}


@pytest.mark.unit
def test_shipped_overrides_collapse_transporte_rodriguez_accent() -> None:
    """Accented and unaccented Rodríguez must collapse."""
    mapping = load_overrides()
    accented, _ = apply("Transporte Rodríguez Asfalto, Inc.", mapping)
    unaccented, _ = apply("Transporte Rodriguez Asfalto, Inc.", mapping)
    assert accented == unaccented == "TRANSPORTE RODRIGUEZ ASFALTO"


@pytest.mark.unit
def test_shipped_overrides_collapse_virella_ing_credential_prefix() -> None:
    """`Ing.` is a credential prefix; bare and prefixed forms must collapse."""
    mapping = load_overrides()
    bare, bare_overridden = apply("Juan O. Virella Sánchez", mapping)
    prefixed, prefixed_overridden = apply("Ing. Juan O. Virella Sánchez", mapping)
    assert bare == prefixed
    assert bare_overridden is True
    assert prefixed_overridden is True


@pytest.mark.unit
def test_shipped_overrides_collapse_om_consulting_engineering_variants() -> None:
    """The ACT 2020 PDF's `O & M CONSULTING ENGINEERING ,P.S.C.` leading-comma
    quirk and ampersand-spacing variants must collapse to one canonical."""
    mapping = load_overrides()
    variants = [
        "O & M CONSULTING ENGINEERING ,P.S.C.",
        "O&M Consulting Engineering",
        "O & M Consulting Engineering, PSC",
    ]
    canonicals = {apply(v, mapping)[0] for v in variants}
    assert len(canonicals) == 1


@pytest.mark.unit
def test_shipped_overrides_collapse_cosiani_typo() -> None:
    """ACUDEN 2024 has the typo `Integraod` vs correct `Integrados`; both must
    collapse to one canonical."""
    mapping = load_overrides()
    typo, typo_ovrd = apply("Cooperativa de Servicios Integraod a la Niñez (COSIANI)", mapping)
    correct, correct_ovrd = apply(
        "Cooperativa de Servicios Integrados a la Niñez (COSIANI)", mapping
    )
    assert typo == correct
    assert typo_ovrd is True
    assert correct_ovrd is True


@pytest.mark.unit
def test_shipped_overrides_collapse_rajohnyari_typo() -> None:
    """ACUDEN 2024 has both `Rajohnyari` (with h) and `Rajonyari` (without h)
    for the same childcare operator; must collapse."""
    mapping = load_overrides()
    with_h, _ = apply("Rajohnyari Day Care & Academy Bilingual School Inc.", mapping)
    without_h, _ = apply("Rajonyari Day Care & Academy Bilingual School Inc.", mapping)
    assert with_h == without_h


@pytest.mark.unit
def test_shipped_overrides_collapse_maritime_transport_truncations() -> None:
    """The ACT 2020 PDF text truncates both the English and Spanish forms; the
    truncated variants must still collapse to the Maritime Transport canonical."""
    mapping = load_overrides()
    english_trunc, en_ovrd = apply("Maritime Transport Authority for Puerto Rico and t", mapping)
    spanish_trunc, sp_ovrd = apply("AUTORIDAD DE TRANSPORTE MARITIMO Y LAS ISLAS MUNIC", mapping)
    assert english_trunc == spanish_trunc
    assert en_ovrd is True
    assert sp_ovrd is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_a, raw_b",
    [
        ("Unlimited Learning Center, Inc.", "Unlimited Lerning Center Inc."),
        ("JJ Investment Group LLC", "JJ Investmentt Group LLC"),
        ("All Access Academics LLC", "All Acess Academics LLC"),
        ("Kiddiecare Pre-School and Tutoring Center LLC", "Kiddiecare Preschool and Tutoring Center LLC"),
        ("Adonai Day Care & Learning Center, Corp.", "Adonai Daycare and Learning Center Corp"),
        ("OCTAGON CONSULTANT GROUP, CORP.", "Octagon Consulting Group LLC"),
        ("CDI Emanuel, Inc.", "CDI Emmanuel Inc"),
        ("Little Kids Adventure Day Care and Leaning Center Inc.", "Little Kids Adventure Day Care Learning Center Inc"),
        ("Topee-Topee, LLC", "Topeee Topee LLC"),
        ("Centro Cuidado Amor Inc.", "Centro de Cuidado Amor Inc"),
    ],
)
def test_shipped_overrides_collapse_layer_c_typo_clusters(raw_a, raw_b) -> None:
    """Layer C: typo/spelling clusters surfaced from the full 1,797-row extraction
    must collapse to one canonical (and not stay split)."""
    mapping = load_overrides()
    ca, _ = apply(raw_a, mapping)
    cb, _ = apply(raw_b, mapping)
    assert ca == cb


@pytest.mark.unit
def test_shipped_overrides_keep_distinct_similar_entities_apart() -> None:
    """Near-duplicate but genuinely distinct entities must NOT be merged."""
    mapping = load_overrides()
    # CMA vs CSA Architects are different firms.
    cma, _ = apply("CMA Architects & Engineers, LLP", mapping)
    csa, _ = apply("CSA Architects & Engineers, LLP", mapping)
    assert cma != csa
