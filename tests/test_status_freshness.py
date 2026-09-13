from datetime import datetime, timedelta, timezone

from scripts.check_status_freshness import validate_status


NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def test_status_freshness_accepts_current_metadata_with_stale_evidence_disclosure():
    payload = {
        "main_sha": "abc123",
        "generated_at": "2026-08-19T12:00:00Z",
        "evidence_snapshot_state": "STALE_NOT_RECERTIFIED",
    }
    assert validate_status(payload, "abc123", now=NOW, max_age=timedelta(days=30)) == []


def test_status_freshness_rejects_wrong_head_and_old_timestamp():
    payload = {
        "main_sha": "old",
        "generated_at": "2026-06-01T00:00:00Z",
        "evidence_snapshot_state": "CURRENT",
    }
    errors = validate_status(payload, "abc123", now=NOW, max_age=timedelta(days=30))
    assert any("main_sha" in error for error in errors)
    assert any("older" in error for error in errors)
