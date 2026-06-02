import json
import logging
from ollama_client import chat_completion, stream_completion
from tools import run_tool, tools_description
from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

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


async def _route(user_message: str) -> tuple:
    """Returns (tool_name | None, params dict, status text)."""
    prompt = ROUTER_PROMPT.format(tools=tools_description())
    try:
        raw = await chat_completion(
            messages=[{"role": "user", "content": user_message}],
            system=prompt,
            temperature=0,
        )
        text = raw.strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            decision = json.loads(text[start:end])
            tool = decision.get("tool")
            if tool:
                params = decision.get("params", {})
                status = TOOL_STATUS.get(tool, f"⚙️ Running {tool}...")
                if tool == "web_search":
                    status = f"🔍 Searching: {params.get('query', '')}..."
                return tool, params, status
    except Exception as e:
        logger.warning(f"Tool routing failed: {e}")
    return None, {}, ""


async def run_agent(user_message: str, history: list, user_memory: list):
    """
    Orchestrates one turn of the agentic loop.

    Returns (status_text | None, async_stream_generator)
    - status_text: shown to user while tool runs (None = no tool used)
    - stream: async generator yielding reply tokens
    """
    tool_name, tool_params, status_text = await _route(user_message)

    tool_context = ""
    if tool_name:
        try:
            result = await run_tool(tool_name, tool_params)
            tool_context = f"\n\n[{tool_name} result]:\n{result}"
            logger.info(f"Tool {tool_name} result: {result[:120]}")
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            status_text = None  # Don't show stale status if tool failed

    messages = history + [{
        "role": "user",
        "content": user_message + tool_context,
    }]

    stream = stream_completion(messages, SYSTEM_PROMPT, user_memory)
    return status_text if tool_name else None, stream
