"""SSRF protections for web tools."""

from __future__ import annotations

from kite.tools.web import _url_blocked


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
