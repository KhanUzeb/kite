"""SSRF protections for web tools."""

from __future__ import annotations

import socket

import pytest

from kite.guardrails.ssrf import url_blocked
from kite.tools.web import _url_blocked


def test_blocks_decimal_localhost() -> None:
    assert _url_blocked("http://2130706433/") == "private network URLs blocked"


def test_blocks_hex_localhost() -> None:
    assert _url_blocked("http://0x7f000001/") == "private network URLs blocked"


def test_blocks_metadata_ip() -> None:
    assert _url_blocked("http://169.254.169.254/latest/meta-data/") == "private network URLs blocked"


def test_blocks_metadata_hostname() -> None:
    assert _url_blocked("http://metadata.google.internal/computeMetadata/v1/") == "local URLs blocked"


def test_blocks_private_ipv6_loopback() -> None:
    assert url_blocked("http://[::1]/") == "private network URLs blocked"
    assert url_blocked("http://[fc00::1]/") == "private network URLs blocked"


def test_blocks_link_local_ipv6() -> None:
    assert url_blocked("http://[fe80::1]/") == "private network URLs blocked"


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

