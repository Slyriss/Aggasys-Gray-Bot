import json
import logging
from ollama_client import chat_completion
from db import save_user_memory

logger = logging.getLogger(__name__)

EXTRACTOR_PROMPT = """Extract important long-term facts about the user from this conversation.

Save: name, role/title, preferences, ongoing projects, location, recurring tasks.
Skip: one-off questions, greetings, generic requests, anything already obvious.

Reply with ONLY a JSON array of short fact strings, or [] if nothing worth saving.
Example: ["Senior network engineer", "Prefers brief technical answers", "Works on client ACME"]"""


async def extract_and_save(user_id: int, user_message: str, assistant_reply: str):
    """Fire-and-forget: extract facts from a turn and persist to DB."""
    try:
        conversation = f"User: {user_message}\nAssistant: {assistant_reply}"
        raw = await chat_completion(
            messages=[{"role": "user", "content": conversation}],
            system=EXTRACTOR_PROMPT,
            temperature=0,
        )
        text = raw.strip()
        start, end = text.find("["), text.rfind("]") + 1
        if start >= 0 and end > start:
            facts = json.loads(text[start:end])
            for fact in facts:
                if isinstance(fact, str) and len(fact.strip()) > 5:
                    await save_user_memory(user_id, fact.strip())
                    logger.info(f"Saved fact for {user_id}: {fact}")
    except Exception as e:
        logger.warning(f"Memory extraction failed for {user_id}: {e}")
