import logging
from db import get_pool
from ollama_client import chat_completion

logger = logging.getLogger(__name__)

INGEST_PROMPT = """You are a wiki compiler for Aggasys, an IT services company in Singapore.

Given a source document, extract structured knowledge and return a JSON array of wiki pages to create or update.

Wiki page categories:
- clients/<name>       : client profile, contacts, preferences, network info, history
- jobs/<type>          : job types, procedures, SLAs
- procedures/<topic>   : internal procedures, escalation paths, checklists
- staff/<topic>        : onboarding, roles, responsibilities

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


async def search_wiki(query: str, limit: int = 3) -> list[dict]:
    """Full-text search across all wiki pages. Returns list of {path, title, content}."""
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT path, title, content,
                  ts_rank(search_vector, plainto_tsquery('english', $1)) AS rank
           FROM wiki_pages
           WHERE search_vector @@ plainto_tsquery('english', $1)
           ORDER BY rank DESC
           LIMIT $2""",
        query, limit
    )
    return [{"path": r["path"], "title": r["title"], "content": r["content"]} for r in rows]


async def get_page(path: str) -> dict | None:
    """Get a single wiki page by path."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT path, title, content, sources, updated_at FROM wiki_pages WHERE path = $1",
        path
    )
    if row:
        return dict(row)
    return None


async def upsert_page(path: str, title: str, content: str, sources: list[str] = None):
    """Create or update a wiki page."""
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO wiki_pages (path, title, content, sources, updated_at)
           VALUES ($1, $2, $3, $4, NOW())
           ON CONFLICT (path) DO UPDATE
           SET title = EXCLUDED.title,
               content = EXCLUDED.content,
               sources = EXCLUDED.sources,
               updated_at = NOW()""",
        path, title, content, sources or []
    )
    logger.info(f"Wiki page upserted: {path}")


async def list_pages(prefix: str = None) -> list[dict]:
    """List all wiki pages, optionally filtered by path prefix."""
    pool = await get_pool()
    if prefix:
        rows = await pool.fetch(
            "SELECT path, title, updated_at FROM wiki_pages WHERE path LIKE $1 ORDER BY path",
            f"{prefix}%"
        )
    else:
        rows = await pool.fetch(
            "SELECT path, title, updated_at FROM wiki_pages ORDER BY path"
        )
    return [dict(r) for r in rows]


async def ingest_document(text: str, source_name: str) -> list[str]:
    """
    Feed a raw document to the LLM wiki compiler.
    Returns list of page paths that were created/updated.
    """
    import json

    prompt = f"Source file: {source_name}\n\n---\n\n{text[:8000]}"  # cap at 8k chars
    try:
        raw = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system=INGEST_PROMPT,
            temperature=0.2,
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
    """Ask the LLM to review the wiki for gaps, contradictions, and stale pages."""
    pages = await list_pages()
    if not pages:
        return "Wiki is empty — nothing to lint yet."

    index = "\n".join(f"- {p['path']}: {p['title']} (updated {p['updated_at']})" for p in pages)

    result = await chat_completion(
        messages=[{"role": "user", "content": f"Wiki index:\n{index}"}],
        system="""You are auditing a company knowledge wiki.
Review the page list and identify:
1. Missing pages that should exist (e.g. a client exists but has no procedures page)
2. Pages likely to be stale
3. Obvious gaps in coverage

Be concise. Return a short markdown list of findings.""",
        temperature=0.3,
    )
    return result
