from __future__ import annotations

import os
import re
from typing import Any


GROUP_CHAT_MODE = os.getenv("HERMES_GROUP_CHAT_MODE", "mention").strip().lower()


def should_process_message(update: Any, bot_username: str | None = None,
                           bot_id: int | None = None, text: str | None = None) -> bool:
    """Return True when Gray should respond to an incoming chat item.

    Private chats are always processed. Group chats default to mention/reply
    gating so Gray can live in teams without answering every line.
    """
    message = getattr(update, "message", None)
    chat = getattr(update, "effective_chat", None)
    chat_type = getattr(chat, "type", None)

    if chat_type in {None, "private"}:
        return True

    if GROUP_CHAT_MODE in {"all", "always"}:
        return True
    if GROUP_CHAT_MODE in {"off", "never"}:
        return False

    content = text
    if content is None and message is not None:
        content = getattr(message, "text", None) or getattr(message, "caption", None) or ""

    if bot_username and _mentions_bot(content or "", bot_username):
        return True

    reply = getattr(message, "reply_to_message", None) if message is not None else None
    reply_user = getattr(reply, "from_user", None) if reply is not None else None
    if reply_user is not None:
        if bot_id is not None and getattr(reply_user, "id", None) == bot_id:
            return True
        if bot_username and getattr(reply_user, "username", "").lower() == bot_username.lower().lstrip("@"):
            return True

    return False


def strip_bot_mention(text: str, bot_username: str | None = None) -> str:
    if not text or not bot_username:
        return text
    username = re.escape(bot_username.lstrip("@"))
    stripped = re.sub(rf"@{username}\b[:,]?\s*", "", text, flags=re.IGNORECASE)
    return stripped.strip()


def _mentions_bot(text: str, bot_username: str) -> bool:
    username = re.escape(bot_username.lstrip("@"))
    return re.search(rf"@{username}\b", text or "", flags=re.IGNORECASE) is not None
