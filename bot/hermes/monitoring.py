from __future__ import annotations


DEFAULT_MONITOR_MAX_CHARS = 3200


def web_monitor_message(query: str, result: str, max_chars: int = DEFAULT_MONITOR_MAX_CHARS) -> str:
    clean_query = (query or "monitor").strip()
    clean_result = (result or "No results found.").strip()
    header = f"Web monitor update: {clean_query}"
    body = _truncate(clean_result, max_chars=max_chars - len(header) - 2)
    return f"{header}\n\n{body}"


def _truncate(text: str, max_chars: int) -> str:
    if max_chars < 20:
        max_chars = 20
    if len(text) <= max_chars:
        return text
    suffix = "\n...[truncated]"
    return text[: max_chars - len(suffix)].rstrip() + suffix
