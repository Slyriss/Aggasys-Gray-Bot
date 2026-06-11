import json
import logging
import httpx
import os
import time
from prompts import SYSTEM_PROMPT

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "24h")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_LIVE_CONCURRENCY = int(os.getenv("OLLAMA_LIVE_CONCURRENCY", "2"))
OLLAMA_BACKGROUND_CONCURRENCY = int(os.getenv("OLLAMA_BACKGROUND_CONCURRENCY", "1"))
MAX_MEMORY_FACTS = int(os.getenv("MAX_MEMORY_FACTS", "12"))
MAX_MEMORY_CHARS = int(os.getenv("MAX_MEMORY_CHARS", "160"))

logger = logging.getLogger(__name__)
_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=10, read=180, write=30, pool=10),
    limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
)
_live_sem = None
_background_sem = None


def _get_sem(background: bool):
    global _live_sem, _background_sem
    if background:
        if _background_sem is None:
            import asyncio
            _background_sem = asyncio.Semaphore(OLLAMA_BACKGROUND_CONCURRENCY)
        return _background_sem
    if _live_sem is None:
        import asyncio
        _live_sem = asyncio.Semaphore(OLLAMA_LIVE_CONCURRENCY)
    return _live_sem


async def close_client():
    await _client.aclose()


def _build_messages(messages: list, system: str, user_memory: list = None) -> list:
    sys = system
    if user_memory:
        trimmed = []
        seen = set()
        for fact in user_memory:
            fact = str(fact).strip()
            if not fact or fact.lower() in seen:
                continue
            seen.add(fact.lower())
            trimmed.append(fact[:MAX_MEMORY_CHARS])
            if len(trimmed) >= MAX_MEMORY_FACTS:
                break
        memory_text = "\n".join(f"- {fact}" for fact in trimmed)
        sys += f"\n\nWhat you remember about this staff member:\n{memory_text}"
    return [{"role": "system", "content": sys}] + messages


def _log_usage(label: str, data: dict, elapsed: float):
    if not data.get("done"):
        return
    total = data.get("total_duration", 0) / 1_000_000_000
    load = data.get("load_duration", 0) / 1_000_000_000
    prompt_tokens = data.get("prompt_eval_count", 0)
    output_tokens = data.get("eval_count", 0)
    eval_duration = data.get("eval_duration", 0) / 1_000_000_000
    tok_per_sec = output_tokens / eval_duration if eval_duration else 0
    logger.info(
        "ollama.%s elapsed=%.2fs total=%.2fs load=%.2fs prompt_tokens=%s output_tokens=%s tok_s=%.2f",
        label, elapsed, total, load, prompt_tokens, output_tokens, tok_per_sec,
    )


async def chat_completion(messages: list, system: str = SYSTEM_PROMPT,
                          user_memory: list = None, temperature: float = 0.7,
                          background: bool = False, label: str = "chat") -> str:
    """Single blocking completion — used for tool routing and memory extraction."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": _build_messages(messages, system, user_memory),
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"temperature": temperature, "num_ctx": OLLAMA_NUM_CTX},
    }
    started = time.monotonic()
    async with _get_sem(background):
        response = await _client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
    _log_usage(label, data, time.monotonic() - started)
    return data["message"]["content"]


async def stream_completion(messages: list, system: str = SYSTEM_PROMPT,
                            user_memory: list = None, label: str = "stream"):
    """Async generator — yields text chunks as tokens arrive from Ollama."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": _build_messages(messages, system, user_memory),
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"num_ctx": OLLAMA_NUM_CTX},
    }
    started = time.monotonic()
    async with _get_sem(background=False):
        async with _client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    data = json.loads(line)
                    if not data.get("done") and "message" in data:
                        yield data["message"]["content"]
                    elif data.get("done"):
                        _log_usage(label, data, time.monotonic() - started)
