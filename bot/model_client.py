import json
import logging
import httpx
import os
import time
from prompts import SYSTEM_PROMPT

MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "deepseek").strip().lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "24h")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_LIVE_CONCURRENCY = int(os.getenv("OLLAMA_LIVE_CONCURRENCY", "2"))
OLLAMA_BACKGROUND_CONCURRENCY = int(os.getenv("OLLAMA_BACKGROUND_CONCURRENCY", "1"))
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
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


def _provider() -> str:
    return MODEL_PROVIDER


def _openai_payload(messages: list, system: str, user_memory: list | None,
                    temperature: float, stream: bool) -> dict:
    return {
        "model": DEEPSEEK_MODEL,
        "messages": _build_messages(messages, system, user_memory),
        "temperature": temperature,
        "stream": stream,
    }


def _deepseek_headers() -> dict:
    return {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }


def _deepseek_chat_url() -> str:
    return f"{DEEPSEEK_BASE_URL}/chat/completions"


def _extract_openai_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or ""


def _extract_openai_delta(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    return delta.get("content") or ""


async def chat_completion(messages: list, system: str = SYSTEM_PROMPT,
                          user_memory: list = None, temperature: float = 0.7,
                          background: bool = False, label: str = "chat") -> str:
    """Single blocking completion — used for tool routing and memory extraction."""
    if _provider() == "deepseek":
        payload = _openai_payload(messages, system, user_memory, temperature, stream=False)
        started = time.monotonic()
        async with _get_sem(background):
            response = await _client.post(
                _deepseek_chat_url(),
                json=payload,
                headers=_deepseek_headers(),
            )
            response.raise_for_status()
            data = response.json()
        usage = data.get("usage") or {}
        logger.info(
            "deepseek.%s elapsed=%.2fs model=%s prompt_tokens=%s completion_tokens=%s",
            label,
            time.monotonic() - started,
            data.get("model", DEEPSEEK_MODEL),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )
        return _extract_openai_text(data)

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
    """Async generator — yields text chunks as tokens arrive from the configured provider."""
    if _provider() == "deepseek":
        payload = _openai_payload(messages, system, user_memory, temperature=0.7, stream=True)
        started = time.monotonic()
        async with _get_sem(background=False):
            async with _client.stream(
                "POST",
                _deepseek_chat_url(),
                json=payload,
                headers=_deepseek_headers(),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line.removeprefix("data:").strip()
                    if chunk == "[DONE]":
                        logger.info(
                            "deepseek.%s elapsed=%.2fs model=%s",
                            label,
                            time.monotonic() - started,
                            DEEPSEEK_MODEL,
                        )
                        break
                    data = json.loads(chunk)
                    text = _extract_openai_delta(data)
                    if text:
                        yield text
        return

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
