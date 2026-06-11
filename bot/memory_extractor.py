import json
import logging
from ollama_client import chat_completion
from db import save_user_memory, save_company_memory
from embedding import embed_text

logger = logging.getLogger(__name__)

EXTRACTOR_PROMPT = """Extract two categories of long-term facts from this conversation exchange.

1. USER FACTS: personal info about the speaker — name, role, preferences, ongoing projects, work style.
2. COMPANY FACTS: business knowledge useful to the whole company — clients, deals, decisions, contacts, vendors, procedures, pricing.

Skip: greetings, generic questions, anything trivial or already common knowledge.

Reply ONLY with valid JSON (no markdown, no explanation):
{
  "user_facts": ["fact1", "fact2"],
  "company_facts": [
    {"fact": "Client ABC prefers evening maintenance windows", "category": "client"},
    {"fact": "Decided to drop vendor XYZ — pricing 40% above market", "category": "decision"}
  ]
}

Valid categories: client, decision, vendor, contact, procedure, project, pricing, general"""


async def extract_and_save(user_id: int, user_message: str, assistant_reply: str):
    """Fire-and-forget: extract user + company facts from a turn and persist to DB."""
    try:
        conversation = f"User: {user_message}\nAssistant: {assistant_reply}"
        raw = await chat_completion(
            messages=[{"role": "user", "content": conversation}],
            system=EXTRACTOR_PROMPT,
            temperature=0,
            background=True,
            label="memory_extract",
        )
        text = raw.strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start < 0 or end <= start:
            return

        data = json.loads(text[start:end])

        for fact in data.get("user_facts", []):
            if isinstance(fact, str) and len(fact.strip()) > 5:
                await save_user_memory(user_id, fact.strip())
                logger.info(f"User fact [{user_id}]: {fact}")

        for item in data.get("company_facts", []):
            if not isinstance(item, dict):
                continue
            fact = item.get("fact", "").strip()
            category = item.get("category", "general")
            if len(fact) > 10:
                emb = None
                try:
                    emb = await embed_text(fact)
                except Exception:
                    pass
                await save_company_memory(
                    fact=fact,
                    category=category,
                    source_user_id=user_id,
                    embedding=emb,
                )
                logger.info(f"Company fact [{category}]: {fact}")

    except Exception as e:
        logger.warning(f"Memory extraction failed for {user_id}: {e}")
