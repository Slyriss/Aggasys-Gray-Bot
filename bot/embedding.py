import httpx
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

async def embed_text(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": text}
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]

def to_pg_vector(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"
