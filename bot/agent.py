import json
import logging
import os
import re
from ollama_client import chat_completion, stream_completion
from tools import run_tool, tools_description
from prompts import SYSTEM_PROMPT
from context_engine import get_context
from url_ingester import extract_urls, fetch_url_text

logger = logging.getLogger(__name__)
ENABLE_LLM_ROUTER = os.getenv("ENABLE_LLM_ROUTER", "0").lower() in {"1", "true", "yes"}
ENABLE_AUTO_CONTEXT = os.getenv("ENABLE_AUTO_CONTEXT", "1").lower() in {"1", "true", "yes"}
ENABLE_URL_FETCH = os.getenv("ENABLE_URL_FETCH", "1").lower() in {"1", "true", "yes"}
MAX_URL_CONTEXT_CHARS = int(os.getenv("MAX_URL_CONTEXT_CHARS", "3000"))

ROUTER_PROMPT = """You are a tool router. Decide if the user message needs a tool.

Tools:
{tools}

Reply with ONLY valid JSON, no explanation:
Tool needed:  {{"tool": "tool_name", "params": {{"key": "value"}}}}
No tool:      {{"tool": null}}"""

TOOL_STATUS = {
    "calculator": "🧮 Calculating...",
    "get_datetime": "🕐 Checking time...",
    "web_search": "🔍 Searching the web...",
    "wiki_search": "📖 Checking company wiki...",
}


def _status_for(tool: str, params: dict) -> str:
    if tool == "web_search":
        return f"🔍 Searching: {params.get('query', '')}..."
    return TOOL_STATUS.get(tool, f"⚙️ Running {tool}...")


def _local_route(user_message: str) -> tuple:
    text = user_message.strip()
    lowered = text.lower()

    if re.fullmatch(r"[0-9\s+\-*/().%^]+", text) or re.match(
        r"^(calculate|calc|what is|what's)\s+[-+*/().0-9\s%^]+$", lowered
    ):
        expression = re.sub(r"^(calculate|calc|what is|what's)\s+", "", text, flags=re.I)
        params = {"expression": expression}
        return "calculator", params, _status_for("calculator", params)

    if any(phrase in lowered for phrase in (
        "what time", "what date", "current time", "current date",
        "date today", "time in singapore", "singapore time", "sgt",
    )):
        return "get_datetime", {}, _status_for("get_datetime", {})

    if lowered.startswith("wiki ") or lowered.startswith("search wiki ") or any(
        phrase in lowered for phrase in (
            "company wiki", "in the wiki", "from the wiki", "client procedure",
            "client info", "client details", "internal procedure",
        )
    ):
        query = re.sub(r"^(search\s+)?wiki\s+", "", text, flags=re.I).strip()
        params = {"query": query or text}
        return "wiki_search", params, _status_for("wiki_search", params)

    if any(phrase in lowered for phrase in (
        "search web", "web search", "look up", "latest", "today's",
        "current news", "news about", "price of", "stock price",
    )):
        query = re.sub(r"^(search\s+web|web\s+search|look\s+up)\s+", "", text, flags=re.I).strip()
        params = {"query": query or text}
        return "web_search", params, _status_for("web_search", params)

    return None, {}, ""


async def _route(user_message: str) -> tuple:
    local = _local_route(user_message)
    if local[0] or not ENABLE_LLM_ROUTER:
        return local

    prompt = ROUTER_PROMPT.format(tools=tools_description())
    try:
        raw = await chat_completion(
            messages=[{"role": "user", "content": user_message}],
            system=prompt,
            temperature=0,
            label="router",
        )
        text = raw.strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            decision = json.loads(text[start:end])
            tool = decision.get("tool")
            if tool:
                params = decision.get("params", {})
                return tool, params, _status_for(tool, params)
    except Exception as e:
        logger.warning(f"Tool routing failed: {e}")
    return None, {}, ""


async def _fetch_url_context(user_message: str) -> tuple[str, str]:
    """
    If the message contains URLs, fetch their content.
    Returns (status_text, context_block).
    """
    if not ENABLE_URL_FETCH:
        return "", ""

    urls = extract_urls(user_message)
    if not urls:
        return "", ""

    url = urls[0]  # process first URL only
    title, text = await fetch_url_text(url)
    if not text:
        return "", ""

    truncated = text[:MAX_URL_CONTEXT_CHARS]
    if len(text) > MAX_URL_CONTEXT_CHARS:
        truncated += "\n[... content truncated ...]"

    context = f"[Web page: {title}]\nURL: {url}\n\n{truncated}"
    status = f"🌐 Reading: {title[:60]}..."
    logger.info(f"URL context fetched: {url} ({len(text)} chars)")
    return status, context


async def run_agent(user_message: str, history: list, user_memory: list,
                    conversation_summary: str = ""):
    """
    Orchestrates one turn: optional tool use + URL fetch + auto-context injection + streaming reply.
    Returns (status_text | None, async_stream_generator).
    """
    tool_name, tool_params, status_text = await _route(user_message)

    tool_context = ""
    url_status = ""

    if tool_name:
        try:
            result = await run_tool(tool_name, tool_params)
            tool_context = f"\n\n[{tool_name} result]:\n{result}"
            logger.info(f"Tool {tool_name}: {result[:120]}")
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            status_text = None
    else:
        # Try URL fetching (only when no tool triggered)
        url_status, url_context = await _fetch_url_context(user_message)
        if url_context:
            tool_context = f"\n\n{url_context}"

    # Auto-inject relevant wiki + company knowledge
    auto_context = ""
    if ENABLE_AUTO_CONTEXT and not tool_name:
        try:
            auto_context = await get_context(user_message)
            if auto_context:
                auto_context = f"\n\n[Relevant company knowledge]\n{auto_context}"
        except Exception as e:
            logger.warning(f"Context retrieval failed: {e}")

    # Build system prompt — prepend conversation summary if available
    system = SYSTEM_PROMPT
    if conversation_summary:
        system += f"\n\n{conversation_summary}"

    messages = history + [{
        "role": "user",
        "content": user_message + tool_context + auto_context,
    }]

    final_status = url_status or (status_text if tool_name else None)
    stream = stream_completion(messages, system, user_memory, label="reply")
    return final_status, stream
