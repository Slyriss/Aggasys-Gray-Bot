from __future__ import annotations

from urllib.parse import urlparse


def exception_type(exc: BaseException) -> str:
    return type(exc).__name__


def safe_url_host(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "unknown-host"
    return host[:120]


def text_size(value: object) -> int:
    return len(str(value))
