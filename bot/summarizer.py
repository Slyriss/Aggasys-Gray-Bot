"""
Conversation summarizer — compresses old history into a rolling summary.
Triggered when a user's raw message count exceeds SUMMARY_TRIGGER (default: 20).
The summary is prepended to the system context so nothing important is lost.
"""
import logging
from ollama_client import chat_completion
from db import (
    get_conversation_history, get_conversation_count,
    save_conversation_summary, get_conversation_summary,
    SUMMARY_TRIGGER_MESSAGES,
)

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = """You are summarizing a conversation for a company executive's AI assistant.

Compress this conversation into a compact summary that preserves:
- Key decisions made
- Important names, clients, or projects mentioned
- Tasks or action items agreed upon
- Any facts the assistant should remember for future turns

Be brief — aim for 3-6 bullet points. No preamble."""


async def maybe_summarize(user_id: int):
    """Check if history is long enough to warrant summarization and do it."""
    count = await get_conversation_count(user_id)
    if count < SUMMARY_TRIGGER_MESSAGES:
        return

    history = await get_conversation_history(user_id, limit=SUMMARY_TRIGGER_MESSAGES)
    if not history:
        return

    conversation_text = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}" for m in history
    )
    try:
        summary = await chat_completion(
            messages=[{"role": "user", "content": conversation_text}],
            system=SUMMARIZE_PROMPT,
            temperature=0.3,
            background=True,
            label="summarize",
        )
        await save_conversation_summary(user_id, summary)
        logger.info(f"Conversation summarized for user {user_id} ({count} messages → summary)")
    except Exception as e:
        logger.warning(f"Summarization failed for {user_id}: {e}")


async def get_summary_context(user_id: int) -> str:
    """Return summary as a context block for injection, or '' if none."""
    summary = await get_conversation_summary(user_id)
    if not summary:
        return ""
    return f"[Earlier conversation summary]\n{summary}"
