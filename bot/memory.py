import json
import logging
import re
import httpx
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """You extract memorable facts about a staff member from a single conversation exchange.
Save only facts that will be useful in future conversations: their name, role, department, ongoing projects, or strong preferences.
Return ONLY a valid JSON array of short fact strings. If nothing is worth saving, return [].

User said: {user_message}
Assistant replied: {assistant_reply}

JSON array:"""

async def extract_facts(user_message: str, assistant_reply: str) -> list[str]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": _EXTRACT_PROMPT.format(
            user_message=user_message,
            assistant_reply=assistant_reply
        )}],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            text = resp.json()["message"]["content"].strip()
            match = re.search(r'\[.*?\]', text, re.DOTALL)
            if match:
                facts = json.loads(match.group())
                return [f for f in facts if isinstance(f, str) and f.strip()]
    except Exception as e:
        logger.debug(f"Fact extraction skipped: {e}")
    return []
