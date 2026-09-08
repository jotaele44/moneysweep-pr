from scripts import audit_hud_drgr_authorized_sources as audit


def test_hcv_is_not_promoted_to_authorized_drgr(tmp_path, monkeypatch):
    source = tmp_path / "pr_hud_hcv.csv"
    source.write_text("Program,Count\nHCV,2\n", encoding="utf-8")
    monkeypatch.setattr(audit, "KNOWN_PATHS", [source])

    receipt = audit.build_receipt(tmp_path / "receipt")

    assert receipt["result_state"] == "PARTIAL_UNRESOLVED"
    assert receipt["records"][0]["classification"] == "PARTIAL_NOT_AUTHORIZED_DRGR"


def test_non_empty_activity_csv_is_candidate_not_certified(tmp_path, monkeypatch):
    source = tmp_path / "HUD_DRGR_activity_export.csv"
    source.write_text(
        "Activity ID,Activity Name,Grant Number\nA-1,Water repair,B-18-DP-72\n", encoding="utf-8"
    )
    monkeypatch.setattr(audit, "KNOWN_PATHS", [source])

    receipt = audit.build_receipt(tmp_path / "receipt")

    assert receipt["result_state"] == "FOUND_AUTHORIZED_CANDIDATE"
    assert receipt["records"][0]["inclusion_decision"] == "eligible_for_hud_drgr_ingest_review"


def test_candidate_keeps_blocker_and_frozen_bytes(tmp_path, monkeypatch):
    source = tmp_path / "candidate.csv"
    raw = b"Activity ID,Name\r\nA-1,Raw  name\r\n"
    source.write_bytes(raw)
    monkeypatch.setattr(audit, "KNOWN_PATHS", [source])
    directory = tmp_path / "receipt"
    receipt = audit.build_receipt(directory)
    row = receipt["records"][0]
    source.write_text("changed source")
    assert (directory / row["snapshot_relative_path"]).read_bytes() == raw
    assert receipt["blocker"]
    assert receipt["authorization"] == "UNPROVEN"
    assert receipt["identity_effect"] == "NONE"


def test_csv_preamble_delimiter_raw_fields_and_blank_row_conservation(tmp_path):
    source = tmp_path / "candidate.csv"
    source.write_text(
        "Report generated\n Activity ID ;Raw  Náme\nA-1;Value\n;\n\n", encoding="utf-8"
    )
    row = audit.inspect_path(source)
    assert row["header"] == [" Activity ID ", "Raw  Náme"]
    assert row["preamble"] == [["Report generated"]]
    assert row["header_record"] == 2
    assert row["delimiter"] == ";"
    assert row["logical_rows"] == 1
    assert row["row_arithmetic"] == {
        "source": 3,
        "retained": 1,
        "excluded_blank": 2,
        "malformed": 0,
    }
    assert row["classification"] == "FOUND_AUTHORIZED_CANDIDATE"


def test_bad_shapes_cannot_be_discovery_candidates(tmp_path):
    samples = [
        "Activity ID,Activity ID\nA-1,A-2\n",
        "Activity ID,Name\nA-1,Name,Extra\n",
        "Activity ID,Name\n,\n\n",
        'Activity ID,Name\nA-1,"unterminated\n',
        "Project name\nUnrelated prose\n",
    ]
    for index, sample in enumerate(samples):
        source = tmp_path / f"candidate-{index}.csv"
        source.write_text(sample)
        assert audit.inspect_path(source)["classification"] != "FOUND_AUTHORIZED_CANDIDATE"


def test_directories_and_missing_paths_preserve_unresolved(tmp_path):
    for path in [tmp_path, tmp_path / "absent.csv"]:
        assert audit.inspect_path(path)["classification"] == "UNRESOLVED"


def test_receipt_cannot_overwrite_previous_snapshot(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(audit, "KNOWN_PATHS", [])
    directory = tmp_path / "receipt"
    audit.build_receipt(directory)
    previous = (directory / "hud_drgr_authorized_pursuit_receipt.json").read_bytes()
    with pytest.raises(FileExistsError):
        audit.build_receipt(directory)
    assert (directory / "hud_drgr_authorized_pursuit_receipt.json").read_bytes() == previous
