"""
URL content fetcher — pulls readable text from a web page.
Used for two flows:
  1. Inline: boss pastes a URL in a message → content injected as context for that reply
  2. Explicit: /ingest <url> → content compiled into wiki pages permanently
"""
import logging
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse
import httpx

logger = logging.getLogger(__name__)
MAX_URL_CHARS = 12000
MAX_URL_BYTES = 1_000_000
MAX_URL_REDIRECTS = 3
BLOCKED_HOSTNAMES = {"localhost"}

_URL_RE = re.compile(
    r'https?://[^\s<>"\']+',
    re.IGNORECASE
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def extract_urls(text: str) -> list[str]:
    """Return all URLs found in a message."""
    return _URL_RE.findall(text)


def is_safe_fetch_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in BLOCKED_HOSTNAMES:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return _is_public_ip(ip)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or _default_port(parsed.scheme), type=socket.SOCK_STREAM)
    except OSError as exc:
        logger.info("URL host resolution failed for %s: %s", host, type(exc).__name__)
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for address in addresses:
        try:
            if not _is_public_ip(ipaddress.ip_address(address)):
                logger.info("Blocking URL host %s resolved to non-public address %s", host, address)
                return False
        except ValueError:
            return False
    return True


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _strip_html(html: str) -> str:
    """Lightweight HTML → plain text without extra dependencies."""
    # Remove scripts, styles, nav, footer
    html = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', ' ', html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Convert block elements to newlines
    html = re.sub(r'<(br|p|div|h[1-6]|li|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Decode common HTML entities
    for ent, char in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                      ('&nbsp;', ' '), ('&quot;', '"'), ('&#39;', "'")]:
        text = text.replace(ent, char)
    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


async def fetch_url_text(url: str) -> tuple[str, str] | tuple[None, None]:
    """
    Fetch a URL and return (title, text) or (None, None) on failure.
    text is truncated to MAX_URL_CHARS.
    """
    try:
        if not is_safe_fetch_url(url):
            logger.info("Blocked unsafe URL fetch target: %s", url)
            return None, None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=8, read=20, write=10, pool=5),
            follow_redirects=False,
            headers=HEADERS,
        ) as client:
            current_url = url
            for _ in range(MAX_URL_REDIRECTS + 1):
                resp = await client.get(current_url)
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return None, None
                    current_url = urljoin(str(resp.url), location)
                    if not is_safe_fetch_url(current_url):
                        logger.info("Blocked unsafe URL redirect target: %s", current_url)
                        return None, None
                    continue
                break
            else:
                logger.info("Too many URL redirects for %s", url)
                return None, None
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                logger.info(f"Skipping non-text URL {url}: {content_type}")
                return None, None
            content_length = resp.headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_URL_BYTES:
                logger.info("Skipping oversized URL %s: %s bytes", url, content_length)
                return None, None
            html = resp.text
            if len(resp.content) > MAX_URL_BYTES:
                logger.info("Skipping oversized URL %s: %s bytes", url, len(resp.content))
                return None, None

        # Extract title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else url

        text = _strip_html(html)
        if len(text) < 100:
            return None, None

        return title, text[:MAX_URL_CHARS]

    except Exception as e:
        logger.warning(f"URL fetch failed for {url}: {e}")
        return None, None
