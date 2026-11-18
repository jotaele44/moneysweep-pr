import ssl
from types import SimpleNamespace

from scripts.check_network_egress import check_https_endpoint


def test_https_egress_requires_tls_12_or_newer(monkeypatch):
    context = SimpleNamespace(minimum_version=None)

    class RawSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class TLSSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def settimeout(self, _timeout):
            pass

        def sendall(self, _data):
            pass

        def recv(self, _size):
            return b"HTTP/1.1 200 OK"

    tls_socket = TLSSocket()
    context.wrap_socket = lambda _raw, server_hostname: tls_socket
    monkeypatch.setattr("scripts.check_network_egress.ssl.create_default_context", lambda: context)
    monkeypatch.setattr(
        "scripts.check_network_egress.socket.create_connection",
        lambda *_args, **_kwargs: RawSocket(),
    )

    result = check_https_endpoint("https://example.test")

    assert result.ok
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2
