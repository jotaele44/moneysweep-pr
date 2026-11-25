import pandas as pd

from scripts import download_fac


class _Session:
    def close(self):
        pass


def test_force_zero_row_fetch_preserves_existing_snapshot(tmp_path, monkeypatch):
    out = tmp_path / "data" / "staging" / "processed" / "pr_single_audits.csv"
    out.parent.mkdir(parents=True)
    pd.DataFrame([{"report_id": "KEEP", "auditee_name": "Existing"}]).to_csv(out, index=False)

    monkeypatch.setattr(download_fac, "build_session", lambda *args, **kwargs: _Session())
    monkeypatch.setattr(download_fac, "_fetch", lambda session, logger: [])

    result = download_fac.run(root=tmp_path, force=True)
    preserved = pd.read_csv(out, dtype=str)
    assert result["status"] == "NO_DATA_PRESERVED"
    assert result["rows"] == 1
    assert preserved.loc[0, "report_id"] == "KEEP"


def test_zero_row_fetch_without_prior_snapshot_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(download_fac, "build_session", lambda *args, **kwargs: _Session())
    monkeypatch.setattr(download_fac, "_fetch", lambda session, logger: [])

    result = download_fac.run(root=tmp_path, force=True)
    out = tmp_path / "data" / "staging" / "processed" / "pr_single_audits.csv"
    assert result["status"] == "NO_DATA"
    assert result["rows"] == 0
    assert not out.exists()
