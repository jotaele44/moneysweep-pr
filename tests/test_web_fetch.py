import json

from scripts.web_fetch import fetch_paginated_json, parse_embedded_json


def test_parse_embedded_json_window_data():
    html = '<script>window.__DATA__ = {"data":[{"id":1,"name":"Acme"}]};</script>'
    result = parse_embedded_json(html)
    assert result == {"data": [{"id": 1, "name": "Acme"}]}


def test_parse_embedded_json_array_data():
    html = '<script>dataLayer = [{"id":42,"value":"x"}];</script>'
    result = parse_embedded_json(html)
    assert result == [{"id": 42, "value": "x"}]


def test_fetch_paginated_json(monkeypatch):
    class DummyResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class DummySession:
        def __init__(self):
            self.calls = 0

        def get(self, url, params=None, timeout=None, allow_redirects=True):
            self.calls += 1
            if self.calls > 2:
                return DummyResponse({"data": []})
            return DummyResponse({"data": [{"id": self.calls}]})

    session = DummySession()
    rows = fetch_paginated_json(
        session,
        "https://example.com/api",
        params={"limit": 1},
        page_param="page",
        page_size_param="per_page",
        page_size=1,
        max_pages=10,
        logger=None,
        items_keys=["data"],
    )
    assert rows == [{"id": 1}, {"id": 2}]
