import httpx
import os

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "disabled").strip().lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "24h")
_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10),
    limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
)


async def close_client():
    await _client.aclose()


async def embed_text(text: str) -> list[float]:
    if EMBEDDING_PROVIDER == "disabled":
        raise RuntimeError("Embeddings are disabled by EMBEDDING_PROVIDER=disabled.")
    if EMBEDDING_PROVIDER != "ollama":
        raise RuntimeError(f"Unsupported EMBEDDING_PROVIDER={EMBEDDING_PROVIDER}.")
    resp = await _client.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": text, "keep_alive": OLLAMA_KEEP_ALIVE}
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def to_pg_vector(embedding: list[float]) -> str:
    """Legacy helper — prefer passing lists directly with pgvector registered."""
    return "[" + ",".join(str(x) for x in embedding) + "]"
