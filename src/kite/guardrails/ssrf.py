"""SSRF protections for user-controlled HTTP(S) URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "0.0.0.0",
        "metadata.google.internal",
        "metadata.google",
    }
)
_BLOCKED_IPS = frozenset(
    {
        "169.254.169.254",
        "100.100.100.200",
        "127.0.0.1",
        "0.0.0.0",
    }
)


def parse_host_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    token = (host or "").strip().lower().rstrip(".")
    if not token:
        return None
    if token in _BLOCKED_HOSTS:
        return ipaddress.ip_address("127.0.0.1")
    if token.isdigit():
        try:
            return ipaddress.IPv4Address(int(token))
        except ValueError:
            return None
    if token.startswith("0x"):
        try:
            return ipaddress.IPv4Address(int(token, 16))
        except ValueError:
            return None
    if token.startswith("0") and len(token) > 1 and token[1:].isdigit():
        try:
            return ipaddress.IPv4Address(int(token, 8))
        except ValueError:
            pass
    try:
        return ipaddress.ip_address(token)
    except ValueError:
        pass
    if token.startswith("[") and token.endswith("]"):
        try:
            return ipaddress.ip_address(token[1:-1])
        except ValueError:
            return None
    return None


def ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if str(ip) in _BLOCKED_IPS:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    literal = parse_host_ip(host)
    if literal is not None:
        return [literal]
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        key = str(ip)
        if key not in seen:
            seen.add(key)
            ips.append(ip)
    return ips


def url_blocked(url: str) -> str | None:
    """Return an error string when the URL must not be fetched, else None."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return "only http(s) URLs allowed"
    host = (parsed.hostname or "").lower()
    if not host:
        return "invalid URL"
    if host in _BLOCKED_HOSTS or host.endswith(".local"):
        return "local URLs blocked"
    literal = parse_host_ip(host)
    if literal is not None and ip_blocked(literal):
        return "private network URLs blocked"
    for ip in resolve_host_ips(host):
        if ip_blocked(ip):
            return "private network URLs blocked"
    return None


class SafeRedirectHandler(HTTPRedirectHandler):
    """Re-validate every redirect destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        err = url_blocked(newurl)
        if err:
            raise URLError(err)
        old = urlparse(req.full_url)
        new = urlparse(newurl)
        if new.scheme not in {"http", "https"}:
            raise URLError("redirect to non-http(s) scheme blocked")
        if old.scheme == "https" and new.scheme == "http":
            raise URLError("https→http downgrade redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_request_url(url: str) -> str | None:
    """Validate immediately before opening a connection (mitigate DNS TOCTOU)."""
    return url_blocked(url)


def guarded_request(url: str, *, headers: dict[str, str] | None = None) -> Request:
    err = validate_request_url(url)
    if err:
        raise URLError(err)
    return Request(url, headers=headers or {})
