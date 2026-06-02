import json
import httpx
import os
from prompts import SYSTEM_PROMPT

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")


def _build_messages(messages: list, system: str, user_memory: list = None) -> list:
    sys = system
    if user_memory:
        memory_text = "\n".join(f"- {fact}" for fact in user_memory)
        sys += f"\n\nWhat you remember about this staff member:\n{memory_text}"
    return [{"role": "system", "content": sys}] + messages


async def chat_completion(messages: list, system: str = SYSTEM_PROMPT,
                          user_memory: list = None, temperature: float = 0.7) -> str:
    """Single blocking completion — used for tool routing and memory extraction."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": _build_messages(messages, system, user_memory),
        "stream": False,
        "options": {"temperature": temperature},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        response.raise_for_status()
        return response.json()["message"]["content"]


async def stream_completion(messages: list, system: str = SYSTEM_PROMPT,
                            user_memory: list = None):
    """Async generator — yields text chunks as tokens arrive from Ollama."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": _build_messages(messages, system, user_memory),
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    data = json.loads(line)
                    if not data.get("done") and "message" in data:
                        yield data["message"]["content"]
