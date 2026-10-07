import pytest

from server.backend import main


@pytest.mark.parametrize("value", ["nan", "inf", "-Infinity", "1e999", float("inf")])
def test_money_numbers_reject_nonfinite(value):
    assert main._num(value) is None


def test_nonfinite_award_does_not_break_contracts_api(monkeypatch):
    from fastapi.testclient import TestClient

    contracts = main.DATA["contracts"].head(1).copy()
    contracts.loc[:, "award_amount"] = "Infinity"
    monkeypatch.setitem(main.DATA, "contracts", contracts)
    with TestClient(main.app) as client:
        response = client.get("/contracts")
    assert response.status_code == 200
    assert response.json()[0]["awardAmount"] is None
