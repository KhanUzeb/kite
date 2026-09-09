"""SSRF protections for web tools."""

from __future__ import annotations

import http.client
import socket
from unittest.mock import MagicMock
from urllib.error import URLError

import pytest

from kite.guardrails.ssrf import (
    SafeRedirectHandler,
    ValidatedHTTPConnection,
    build_safe_opener,
    host_blocked,
    url_blocked,
)
from kite.tools.web import _url_blocked, unwrap_tracking_url


def test_blocks_decimal_localhost() -> None:
    assert _url_blocked("http://2130706433/") == "private network URLs blocked"


def test_blocks_hex_localhost() -> None:
    assert _url_blocked("http://0x7f000001/") == "private network URLs blocked"


def test_blocks_metadata_ip() -> None:
    assert _url_blocked("http://169.254.169.254/latest/meta-data/") == "private network URLs blocked"


def test_blocks_metadata_hostname() -> None:
    assert _url_blocked("http://metadata.google.internal/computeMetadata/v1/") == "local URLs blocked"


def test_blocks_docker_internal_host() -> None:
    assert _url_blocked("http://host.docker.internal/api") == "local URLs blocked"


def test_blocks_internal_suffix() -> None:
    assert host_blocked("service.corp.internal") == "local URLs blocked"
    assert url_blocked("https://api.staging.internal/health") == "local URLs blocked"


def test_blocks_localhost_suffix() -> None:
    assert host_blocked("app.localhost") == "local URLs blocked"


def test_blocks_private_ipv6_loopback() -> None:
    assert url_blocked("http://[::1]/") == "private network URLs blocked"
    assert url_blocked("http://[fc00::1]/") == "private network URLs blocked"


def test_blocks_link_local_ipv6() -> None:
    assert url_blocked("http://[fe80::1]/") == "private network URLs blocked"


def test_blocks_non_http_schemes() -> None:
    assert url_blocked("file:///etc/passwd") == "only http(s) URLs allowed"
    assert url_blocked("gopher://example.com/") == "only http(s) URLs allowed"


def test_allows_public_https() -> None:
    assert _url_blocked("https://example.com/doc") is None


def test_dns_rebinding_blocked_when_resolution_is_private(monkeypatch) -> None:
    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: ANN001
        if host == "evil.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        raise OSError("unknown host")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert url_blocked("https://evil.example/path") == "private network URLs blocked"


def test_dns_rebinding_public_first_private_on_recheck(monkeypatch) -> None:
    calls = {"n": 0}

    def flip_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", flip_getaddrinfo)
    assert url_blocked("https://rebind.example/") is None
    assert url_blocked("https://rebind.example/") == "private network URLs blocked"


def test_connect_blocks_private_peer(monkeypatch) -> None:
    conn = ValidatedHTTPConnection("example.com")
    mock_sock = MagicMock()
    mock_sock.getpeername.return_value = ("127.0.0.1", 80)

    def fake_super_connect(self) -> None:  # noqa: ANN001
        self.sock = mock_sock

    monkeypatch.setattr(http.client.HTTPConnection, "connect", fake_super_connect)
    with pytest.raises(OSError, match="private network URLs blocked"):
        conn.connect()


def test_redirect_limit_blocks_hops() -> None:
    handler = SafeRedirectHandler()
    handler.max_redirects = 2
    handler.redirect_count = 2
    req = MagicMock()
    req.full_url = "https://example.com/a"
    with pytest.raises(URLError, match="too many redirects"):
        handler.redirect_request(req, None, 302, "", {}, "https://example.com/next")


def test_build_safe_opener_includes_validated_handlers() -> None:
    opener = build_safe_opener(max_redirects=3)
    handlers = {type(h).__name__ for h in opener.handlers}
    assert "_ValidatedHTTPHandler" in handlers
    assert "_ValidatedHTTPSHandler" in handlers


def test_unwrap_tracking_url_blocks_localhost_target() -> None:
    wrapped = "https://duckduckgo.com/l/?uddg=http%3A%2F%2F127.0.0.1%2Fsecret"
    assert unwrap_tracking_url(wrapped) == wrapped
