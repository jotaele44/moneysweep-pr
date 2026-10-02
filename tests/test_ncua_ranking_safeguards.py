from scripts import download_ncua


class _Session:
    def close(self):
        pass


def test_ncua_schema_carries_origin_and_scope():
    assert "origin" in download_ncua.NCUA_COLUMNS
    assert "financial_scope" in download_ncua.NCUA_COLUMNS


def test_materialized_ncua_seeds_are_explicitly_labeled(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(download_ncua, "_session", lambda: _Session())
    monkeypatch.setattr(download_ncua, "_fetch_ncua_search_api", lambda session, logger: [])
    monkeypatch.setattr(download_ncua, "_fetch_ncua_bulk", lambda session, logger: [])

    result = download_ncua.run(root=tmp_path, force=True)
    df = pd.read_csv(result["path"], dtype=str)
    assert set(df["origin"]) == {"FALLBACK_SEED"}
    aggregate = df[df["cu_number"] == "ALL_PR"].iloc[0]
    institutions = df[df["cu_number"] != "ALL_PR"]
    assert aggregate["financial_scope"] == "AGGREGATE_STATEWIDE"
    assert set(institutions["financial_scope"]) == {"INSTITUTION_WIDE"}
