import math
import re
import logging
from datetime import datetime
import pytz
from hermes import ActionRisk, HermesAction, HermesPolicy
from hermes.audit import record_decision

logger = logging.getLogger(__name__)
_policy = HermesPolicy()

TOOLS_SCHEMA = [
    {
        "name": "calculator",
        "description": "Evaluate a math expression. Examples: '12 * 15', 'sqrt(144)', '15% of 200'",
    },
    {
        "name": "get_datetime",
        "description": "Get the current date and time in Singapore (SGT, UTC+8).",
    },
    {
        "name": "web_search",
        "description": "Search the web for current news, prices, or facts not in training data.",
    },
    {
        "name": "wiki_search",
        "description": "Search the Aggasys company wiki for clients, jobs, procedures, or internal knowledge.",
    },
]


def _safe_calc(expr: str) -> float:
    # Handle "X% of Y"
    m = re.match(r'^(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)$', expr.strip(), re.I)
    if m:
        return float(m.group(1)) / 100 * float(m.group(2))

    # Strip anything that isn't numbers, operators, parens, dots, spaces
    safe = re.sub(r'[^0-9+\-*/().^ ]', '', expr)
    safe = safe.replace('^', '**')

    code = compile(safe, '<calc>', 'eval')
    # Only allow names that exist in math module
    for name in code.co_names:
        if not hasattr(math, name):
            raise ValueError(f"Disallowed name: {name}")
    return eval(code, {"__builtins__": {}}, vars(math))


async def calculator(expression: str) -> str:
    try:
        result = _safe_calc(expression)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Could not evaluate '{expression}': {e}"


async def get_datetime() -> str:
    sgt = pytz.timezone("Asia/Singapore")
    now = datetime.now(sgt)
    return now.strftime("Current Singapore time: %A, %d %B %Y, %I:%M %p SGT")


async def web_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return "No results found."
        parts = []
        for r in results:
            parts.append(f"{r['title']}\n{r['body']}\nSource: {r['href']}")
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Web search failed: {e}")
        return f"Search failed: {e}"


async def wiki_search(query: str) -> str:
    try:
        from wiki import search_wiki
        results = await search_wiki(query, limit=3)
        if not results:
            return "No wiki pages found for that query."
        parts = []
        for r in results:
            parts.append(f"### {r['title']} ({r['path']})\n{r['content']}")
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Wiki search failed: {e}")
        return f"Wiki search failed: {e}"


async def run_tool(name: str, params: dict) -> str:
    risk = ActionRisk.READ_ONLY if name in {"calculator", "get_datetime", "web_search", "wiki_search"} else ActionRisk.MEDIUM
    action = HermesAction(
        name=name,
        description=f"Run tool `{name}`",
        risk=risk,
        params=params,
    )
    decision = _policy.decide(action)
    await record_decision(decision)
    if decision.needs_confirmation:
        return decision.confirmation_prompt or "Hermes requires confirmation before this action."
    if not decision.allowed:
        return f"Hermes blocked this action: {decision.reason}"

    if name == "calculator":
        return await calculator(params.get("expression", ""))
    if name == "get_datetime":
        return await get_datetime()
    if name == "web_search":
        return await web_search(params.get("query", ""))
    if name == "wiki_search":
        return await wiki_search(params.get("query", ""))
    return f"Unknown tool: {name}"


def tools_description() -> str:
    return "\n".join(f"- {t['name']}: {t['description']}" for t in TOOLS_SCHEMA)
