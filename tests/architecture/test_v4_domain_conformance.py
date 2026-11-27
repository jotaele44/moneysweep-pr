from scripts.audit_v4_domain_conformance import audit


def test_v4_domain_conformance_is_structurally_clean():
    report = audit()
    assert report["state"] == "OPEN"
    assert report["source_count"] == 167
    assert report["unique_source_ids"] == 167
    assert report["mapped_count"] == 165
    assert report["partial_count"] == 2
    assert report["unmapped_or_unresolved_count"] == 0
    assert report["bounded_blocker_count"] == 2
    assert report["partial_source_ids"] == [
        "prasa_completed_projects_ppp",
        "prasa_consulting_engineer_ppp",
    ]
    assert report["partial_source_ids"] == report["bounded_blocker_source_ids"]
    assert report["structural_errors"] == []
    assert report["arithmetic_closure"] == "PASS"
