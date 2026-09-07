"""SSRF protections for web tools."""

from __future__ import annotations

import ipaddress

from kite.tools.web import _parse_host_ip, _url_blocked


def test_blocks_decimal_localhost() -> None:
    assert _url_blocked("http://2130706433/") == "private network URLs blocked"


def test_blocks_hex_localhost() -> None:
    assert _url_blocked("http://0x7f000001/") == "private network URLs blocked"


def test_blocks_metadata_ip() -> None:
    assert _url_blocked("http://169.254.169.254/latest/meta-data/") == "private network URLs blocked"


def test_blocks_metadata_hostname() -> None:
    assert _url_blocked("http://metadata.google.internal/computeMetadata/v1/") == "local URLs blocked"


def test_allows_public_https() -> None:
    assert _url_blocked("https://example.com/doc") is None


def test_parse_host_ip_ipv4_mapped() -> None:
    ip = _parse_host_ip("::ffff:127.0.0.1")
    assert ip is not None
    assert ip.ipv4_mapped == ipaddress.IPv4Address("127.0.0.1")
    assert ip.is_loopback
