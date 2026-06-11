"""
URL content fetcher — pulls readable text from a web page.
Used for two flows:
  1. Inline: boss pastes a URL in a message → content injected as context for that reply
  2. Explicit: /ingest <url> → content compiled into wiki pages permanently
"""
import logging
import re
import httpx

logger = logging.getLogger(__name__)
MAX_URL_CHARS = 12000

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
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=8, read=20, write=10, pool=5),
            follow_redirects=True,
            headers=HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                logger.info(f"Skipping non-text URL {url}: {content_type}")
                return None, None
            html = resp.text

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
