import logging
import os
from db import get_pool
from model_client import chat_completion
from embedding import embed_text

logger = logging.getLogger(__name__)
MAX_WIKI_CONTENT_CHARS = int(os.getenv("MAX_WIKI_CONTENT_CHARS", "1800"))
MAX_INGEST_CHARS = int(os.getenv("MAX_INGEST_CHARS", "8000"))

INGEST_PROMPT = """You are a wiki compiler for Aggasys, an IT services company in Singapore.

Given a source document, extract structured knowledge and return a JSON array of wiki pages to create or update.

Wiki page categories:
- clients/<name>       : client profile, contacts, preferences, network info, history
- jobs/<type>          : job types, procedures, SLAs
- procedures/<topic>   : internal procedures, escalation paths, checklists
- staff/<topic>        : onboarding, roles, responsibilities
- decisions/<topic>    : key business or technical decisions with rationale
- contacts/<name>      : vendors, partners, key external contacts

Each page must be a rich markdown document with all relevant facts, cross-references to related pages, and a "Last updated from:" footer.

Return ONLY a JSON array:
[
  {
    "path": "clients/acme",
    "title": "ACME Corporation",
    "content": "# ACME Corporation\\n\\n## Overview\\n...",
    "sources": ["acme_export.csv"]
  }
]"""


async def _embed_page(text: str) -> list | None:
    try:
        return await embed_text(text[:2000])
    except Exception as e:
        logger.warning(f"Wiki embedding failed: {e}")
        return None


async def search_wiki(query: str, limit: int = 3) -> list[dict]:
    """Hybrid search: vector similarity + full-text, merged and deduplicated."""
    pool = await get_pool()
    results: dict[str, dict] = {}

    # Vector search
    try:
        qemb = await embed_text(query)
        rows = await pool.fetch(
            """SELECT path, title, content,
                      1 - (embedding <=> $1) AS score
               FROM wiki_pages
               WHERE embedding IS NOT NULL
               ORDER BY embedding <=> $1
               LIMIT $2""",
            qemb, limit
        )
        for r in rows:
            if r["score"] > 0.40:
                content = r["content"]
                if len(content) > MAX_WIKI_CONTENT_CHARS:
                    content = content[:MAX_WIKI_CONTENT_CHARS].rsplit("\n", 1)[0] + "\n..."
                results[r["path"]] = {
                    "path": r["path"], "title": r["title"],
                    "content": content, "score": float(r["score"])
                }
    except Exception as e:
        logger.warning(f"Vector wiki search failed: {e}")

    # Full-text search as complement
    try:
        rows = await pool.fetch(
            """SELECT path, title, content,
                      ts_rank(search_vector, plainto_tsquery('english', $1)) AS rank
               FROM wiki_pages
               WHERE search_vector @@ plainto_tsquery('english', $1)
               ORDER BY rank DESC
               LIMIT $2""",
            query, limit
        )
        for r in rows:
            if r["path"] not in results:
                content = r["content"]
                if len(content) > MAX_WIKI_CONTENT_CHARS:
                    content = content[:MAX_WIKI_CONTENT_CHARS].rsplit("\n", 1)[0] + "\n..."
                results[r["path"]] = {
                    "path": r["path"], "title": r["title"],
                    "content": content, "score": float(r["rank"])
                }
    except Exception as e:
        logger.warning(f"Full-text wiki search failed: {e}")

    return sorted(results.values(), key=lambda x: x["score"], reverse=True)[:limit]


async def get_page(path: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT path, title, content, sources, updated_at FROM wiki_pages WHERE path = $1",
        path
    )
    return dict(row) if row else None


async def upsert_page(path: str, title: str, content: str, sources: list[str] = None):
    pool = await get_pool()
    embedding = await _embed_page(f"{title}\n{content}")
    await pool.execute(
        """INSERT INTO wiki_pages (path, title, content, sources, embedding, updated_at)
           VALUES ($1, $2, $3, $4, $5, NOW())
           ON CONFLICT (path) DO UPDATE
           SET title = EXCLUDED.title,
               content = EXCLUDED.content,
               sources = EXCLUDED.sources,
               embedding = EXCLUDED.embedding,
               updated_at = NOW()""",
        path, title, content, sources or [], embedding
    )
    logger.info(f"Wiki page upserted: {path}")


async def list_pages(prefix: str = None) -> list[dict]:
    pool = await get_pool()
    if prefix:
        rows = await pool.fetch(
            "SELECT path, title, updated_at FROM wiki_pages WHERE path LIKE $1 ORDER BY path",
            f"{prefix}%"
        )
    else:
        rows = await pool.fetch("SELECT path, title, updated_at FROM wiki_pages ORDER BY path")
    return [dict(r) for r in rows]


async def ingest_document(text: str, source_name: str) -> list[str]:
    import json

    prompt = f"Source file: {source_name}\n\n---\n\n{text[:MAX_INGEST_CHARS]}"
    try:
        raw = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system=INGEST_PROMPT,
            temperature=0.2,
            label="wiki_ingest",
        )
        text_raw = raw.strip()
        start, end = text_raw.find("["), text_raw.rfind("]") + 1
        if start < 0 or end <= start:
            logger.warning(f"Ingest returned no JSON array for {source_name}")
            return []

        pages = json.loads(text_raw[start:end])
        updated = []
        for page in pages:
            if all(k in page for k in ("path", "title", "content")):
                await upsert_page(
                    path=page["path"],
                    title=page["title"],
                    content=page["content"],
                    sources=page.get("sources", [source_name]),
                )
                updated.append(page["path"])
        return updated
    except Exception as e:
        logger.error(f"Ingest failed for {source_name}: {e}")
        return []


async def lint_wiki() -> str:
    pages = await list_pages()
    if not pages:
        return "Wiki is empty — nothing to lint yet."

    index = "\n".join(
        f"- {p['path']}: {p['title']} (updated {p['updated_at']})" for p in pages
    )
    return await chat_completion(
        messages=[{"role": "user", "content": f"Wiki index:\n{index}"}],
        system="""You are auditing a company knowledge wiki.
Review the page list and identify:
1. Missing pages that should exist
2. Pages likely to be stale
3. Obvious gaps in coverage
Be concise. Return a short markdown list of findings.""",
        temperature=0.3,
        label="wiki_lint",
    )
