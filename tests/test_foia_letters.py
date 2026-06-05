"""Tests for the FOIA letter generation system.

Covers:
- Letter existence and correct template selection per jurisdiction
- Required substitutions are present; non-requester placeholders are filled
- Deterministic regeneration (byte-identical to committed letters)
- Pre-submission validator rejects stub requester config
- Dashboard payload includes letter entries for the foia gate
"""
from __future__ import annotations

import json

import pytest

from scripts import build_foia_letters as bfl
from scripts import build_foia_tracker as bft
from scripts import build_dashboard_explorer as bde

REPO_ROOT = bft.REPO_ROOT


# --------------------------------------------------------------------------- #
# letter existence and content
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_letter_files_exist_for_all_requests():
    queue = bft.build_rows(REPO_ROOT)
    for row in queue:
        letter = REPO_ROOT / bfl.OUT_DIR / f"{row['request_id']}.md"
        assert letter.exists(), f"missing letter: {letter}"


@pytest.mark.unit
def test_letters_use_correct_template_per_jurisdiction():
    entries = bfl.build_rows(REPO_ROOT)
    for e in entries:
        content = e["content"]
        jur = e["jurisdiction"].strip().upper()
        if jur == "PR":
            assert "Ley 141-2019" in content, f"{e['request_id']}: PR letter missing Ley 141-2019"
            assert "Oficial de Acceso" in content, f"{e['request_id']}: PR letter missing Oficial de Acceso"
        elif jur == "US":
            assert "5 U.S.C." in content, f"{e['request_id']}: US letter missing 5 U.S.C."
            assert "FOIA Officer" in content, f"{e['request_id']}: US letter missing FOIA Officer"


@pytest.mark.unit
def test_letters_have_required_substitutions():
    entries = bfl.build_rows(REPO_ROOT)
    for e in entries:
        content = e["content"]
        # target_agency, record_type, and request_id must be in the body
        assert e["request_id"] in content, f"{e['request_id']}: request_id not in letter body"
        # no un-replaced data placeholders (requester placeholders are expected until PR 9)
        for key in ("target_agency", "record_type", "request_id"):
            assert "{{" + key + "}}" not in content, f"{e['request_id']}: {{{{{key}}}}} not replaced"


@pytest.mark.unit
def test_letters_check_passes():
    entries = bfl.build_rows(REPO_ROOT)
    assert bfl.check(entries, REPO_ROOT) == []


@pytest.mark.unit
def test_letters_cover_both_jurisdictions():
    entries = bfl.build_rows(REPO_ROOT)
    jurisdictions = {e["jurisdiction"].upper() for e in entries}
    assert "PR" in jurisdictions
    assert "US" in jurisdictions


@pytest.mark.unit
def test_letter_count_matches_queue():
    queue = bft.build_rows(REPO_ROOT)
    entries = bfl.build_rows(REPO_ROOT)
    assert len(entries) == len(queue)


# --------------------------------------------------------------------------- #
# deterministic regeneration
# --------------------------------------------------------------------------- #

@pytest.mark.integration
def test_letters_regenerate_identically():
    entries = bfl.build_rows(REPO_ROOT)
    for e in entries:
        committed = (REPO_ROOT / e["path"]).read_text(encoding="utf-8")
        assert committed == e["content"], f"{e['request_id']}: committed letter differs from generated"


# --------------------------------------------------------------------------- #
# pre-submission validator
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_validate_foia_submission_not_ready_with_stub_config():
    from scripts.validate_foia_submission_ready import validate
    problems = validate(REPO_ROOT)
    # stub config has {{placeholders}} — validator must flag them
    assert any("placeholder" in p.lower() for p in problems), \
        f"expected placeholder errors, got: {problems}"


# --------------------------------------------------------------------------- #
# dashboard includes letter entries
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_dashboard_payload_includes_foia_letters():
    data = bde.build_data(REPO_ROOT)
    letters = data.get("letters", [])
    assert len(letters) == 9, f"expected 9 letter entries in dashboard, got {len(letters)}"
    for letter in letters:
        assert letter["format"] == "md", f"letter entry has wrong format: {letter}"
        assert letter["gate"] == "foia", f"letter entry has wrong gate: {letter}"
        assert letter["status"] == "done", f"letter not marked done on disk: {letter}"


@pytest.mark.unit
def test_dashboard_letters_tab_marker():
    html = bde.build_html(REPO_ROOT)
    assert 'id="letters"' in html, "Letters tab section missing from dashboard HTML"
    assert "FOIA" in html
