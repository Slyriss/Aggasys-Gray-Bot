"""
Retrieves relevant company context for a query: wiki pages + company memory.
Injected automatically into every agent turn so the boss never has to ask explicitly.
"""
import logging
import os
from embedding import embed_text
from wiki import search_wiki
from db import semantic_search_company_memory, text_search_company_memory
from log_safety import exception_type

logger = logging.getLogger(__name__)
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "1400"))


async def get_context(query: str) -> str:
    """Return a formatted context block for injection into the agent prompt, or '' if nothing relevant."""
    emb = None
    try:
        emb = await embed_text(query)
    except Exception as e:
        logger.warning("Context engine embedding failed: %s", exception_type(e))

    # Parallel retrieval
    wiki_results = await search_wiki(query, limit=2)

    company_facts = []
    if emb:
        company_facts = await semantic_search_company_memory(emb, limit=6)
    if not company_facts:
        company_facts = await text_search_company_memory(query, limit=5)

    if not wiki_results and not company_facts:
        return ""

    parts = []

    if company_facts:
        facts_text = "\n".join(f"- {f}" for f in company_facts[:5])
        parts.append(f"[Company knowledge]\n{facts_text}")

    for page in wiki_results:
        content = page["content"]
        if len(content) > 700:
            content = content[:700].rsplit("\n", 1)[0] + "\n..."
        parts.append(f"[Wiki: {page['title']}]\n{content}")

    combined = "\n\n".join(parts)
    if len(combined) > MAX_CONTEXT_CHARS:
        combined = combined[:MAX_CONTEXT_CHARS].rsplit("\n", 1)[0] + "\n..."
    return combined
