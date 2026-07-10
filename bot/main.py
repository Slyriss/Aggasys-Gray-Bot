import asyncio
from collections import deque
import logging
import os
import time
from functools import wraps
from dotenv import load_dotenv
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    filters, ContextTypes
)
from agent import run_agent
from db import (
    get_conversation_history, save_message,
    get_user_memory, clear_conversation,
    get_user_data_counts, delete_user_data,
    save_note, get_recent_notes, search_notes,
    save_task, get_open_tasks, complete_task, get_all_tasks,
    get_conversation_count, SUMMARY_TRIGGER_MESSAGES,
    create_standup_session, get_open_standup_session, save_standup_update,
    close_standup_session, get_recent_hermes_audit,
    get_pending_hermes_approvals, resolve_hermes_approval,
    create_hermes_job, get_hermes_jobs, pause_hermes_job, remove_hermes_job,
    resume_hermes_job,
    get_hermes_approval, get_hermes_approval_counts, get_hermes_scheduler_health,
    close_pool as close_db_pool,
)
from memory_extractor import extract_and_save
from summarizer import maybe_summarize, get_summary_context
from model_client import close_client as close_model_client
from embedding import close_client as close_embedding_client, embed_text
from wiki import list_pages, ingest_document, lint_wiki, search_wiki
from db import semantic_search_company_memory, text_search_company_memory
from hermes import ActionRisk, ActionDecision, ActionStatus, HermesAction, HermesPolicy
from hermes.audit import record_decision
from hermes.approvals import approval_summary, create_approval_from_decision
from hermes.chat_policy import should_process_message, strip_bot_mention
from hermes.scheduler import HermesScheduler, next_daily_run, parse_daily_time, summary_recipient_tier
from hermes.workflows import (
    looks_like_standup_update,
    missing_standup_participants,
    parse_participants,
    standup_chase_message,
    summarize_standup_updates,
)
from preflight import collect_preflight_report, render_report

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "6"))
MEMORY_QUEUE_SIZE = int(os.getenv("MEMORY_QUEUE_SIZE", "100"))
MEMORY_WORKERS = int(os.getenv("MEMORY_WORKERS", "1"))
RATE_LIMIT_MESSAGES = int(os.getenv("RATE_LIMIT_MESSAGES", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
MAX_DOCUMENT_BYTES = int(os.getenv("MAX_DOCUMENT_BYTES", "5242880"))
MAX_VOICE_BYTES = int(os.getenv("MAX_VOICE_BYTES", "10485760"))
MAX_PHOTO_BYTES = int(os.getenv("MAX_PHOTO_BYTES", "5242880"))

EDIT_INTERVAL = 1.2
EDIT_MIN_CHARS = 40

_ALLOWED_RAW = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = {
    int(uid.strip()) for uid in _ALLOWED_RAW.split(",") if uid.strip().isdigit()
}
_ADMIN_RAW = os.getenv("ADMIN_USERS", "")
ADMIN_USERS: set[int] = {
    int(uid.strip()) for uid in _ADMIN_RAW.split(",") if uid.strip().isdigit()
}
_OPERATOR_RAW = os.getenv("OPERATOR_USERS", "")
OPERATOR_USERS: set[int] = {
    int(uid.strip()) for uid in _OPERATOR_RAW.split(",") if uid.strip().isdigit()
}

_memory_queue = None
_memory_workers = []
_hermes_policy = HermesPolicy()
_hermes_scheduler = None
_rate_limit_buckets: dict[int, deque[float]] = {}
SUMMARY_RECIPIENT_TIERS = {"chat", "admins", "both"}


def _role_count_summary(user_ids: set[int]) -> str:
    return f"{len(user_ids)} user(s)"


def _is_allowed(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USERS


def _is_operator(user_id: int) -> bool:
    return _is_admin(user_id) or user_id in OPERATOR_USERS


def _is_private_chat(update: Update) -> bool:
    return getattr(update.effective_chat, "type", None) == "private"


async def _require_private_chat(update: Update, command_name: str) -> bool:
    if _is_private_chat(update):
        return True
    decision = ActionDecision(
        status=ActionStatus.DENIED,
        reason=f"{command_name} exposes personal Gray data and must run in private chat.",
        action=HermesAction(
            name=f"private_chat_required:{command_name}",
            description="Rejected a personal-data command outside private chat.",
            actor_user_id=update.effective_user.id,
            chat_id=update.effective_chat.id,
            risk=ActionRisk.READ_ONLY,
            params={"command": command_name},
        ),
    )
    await record_decision(decision, status="blocked_private_chat")
    await update.message.reply_text("Please use this command in a private chat with Gray.")
    return False


async def _require_admin(update: Update) -> bool:
    if _is_admin(update.effective_user.id):
        return True
    await _audit_rbac_denial(update, "admin")
    await update.message.reply_text("Restricted to Gray admins.")
    return False


async def _require_operator(update: Update) -> bool:
    if _is_operator(update.effective_user.id):
        return True
    await _audit_rbac_denial(update, "operator")
    await update.message.reply_text("Restricted to Gray operators.")
    return False


async def _audit_rbac_denial(update: Update, required_role: str) -> None:
    decision = ActionDecision(
        status=ActionStatus.DENIED,
        reason=f"User lacks required Gray role: {required_role}.",
        action=HermesAction(
            name=f"rbac_denied:{required_role}",
            description="Rejected a command before execution because the user lacked the required role.",
            actor_user_id=update.effective_user.id,
            chat_id=update.effective_chat.id,
            risk=ActionRisk.READ_ONLY,
            params={
                "required_role": required_role,
                "username": getattr(update.effective_user, "username", None),
            },
        ),
    )
    await record_decision(decision, status="blocked_rbac")


async def _audit_rate_limit(update: Update, retry_after_seconds: int) -> None:
    decision = ActionDecision(
        status=ActionStatus.DENIED,
        reason="User exceeded Gray rate limit.",
        action=HermesAction(
            name="rate_limited",
            description="Rejected a Telegram update before execution because the user exceeded the rate limit.",
            actor_user_id=update.effective_user.id,
            chat_id=update.effective_chat.id,
            risk=ActionRisk.READ_ONLY,
            params={
                "retry_after_seconds": retry_after_seconds,
                "limit": RATE_LIMIT_MESSAGES,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            },
        ),
    )
    await record_decision(decision, status="blocked_rate_limit")


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} bytes"


async def _audit_upload_size_denial(update: Update, upload_kind: str, size: int, limit: int) -> None:
    decision = ActionDecision(
        status=ActionStatus.DENIED,
        reason=f"{upload_kind} upload exceeded configured size limit.",
        action=HermesAction(
            name=f"upload_too_large:{upload_kind}",
            description="Rejected a Telegram upload before download because it exceeded the configured limit.",
            actor_user_id=update.effective_user.id,
            chat_id=update.effective_chat.id,
            risk=ActionRisk.READ_ONLY,
            params={
                "upload_kind": upload_kind,
                "size_bytes": size,
                "limit_bytes": limit,
            },
        ),
    )
    await record_decision(decision, status="blocked_upload_size")


async def _reject_oversize_upload(update: Update, upload_kind: str, size: int | None, limit: int) -> bool:
    if limit <= 0 or size is None or size <= limit:
        return False
    await _audit_upload_size_denial(update, upload_kind, size, limit)
    await update.message.reply_text(
        f"That {upload_kind} is too large ({_format_bytes(size)}). "
        f"Gray accepts up to {_format_bytes(limit)} for {upload_kind} uploads."
    )
    return True


async def _within_rate_limit(update: Update) -> bool:
    if RATE_LIMIT_MESSAGES <= 0 or RATE_LIMIT_WINDOW_SECONDS <= 0:
        return True
    if not update.effective_user:
        return True

    now = time.monotonic()
    bucket = _rate_limit_buckets.setdefault(update.effective_user.id, deque())
    while bucket and now - bucket[0] >= RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_MESSAGES:
        retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        await _audit_rate_limit(update, retry_after)
        await update.message.reply_text(f"Rate limit reached. Try again in {retry_after}s.")
        return False

    bucket.append(now)
    return True


def _rate_limited(handler):
    @wraps(handler)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and _is_allowed(update.effective_user.id):
            if not await _within_rate_limit(update):
                return
        return await handler(update, context)

    return wrapped


def _bot_identity(context: ContextTypes.DEFAULT_TYPE) -> tuple[str | None, int | None]:
    bot = getattr(context, "bot", None)
    username = os.getenv("GRAY_BOT_USERNAME") or getattr(bot, "username", None)
    bot_id = getattr(bot, "id", None)
    return username, bot_id


def _safe_update_user_id(update) -> int | None:
    user = getattr(update, "effective_user", None)
    return getattr(user, "id", None)


def _safe_update_chat_id(update) -> int | None:
    chat = getattr(update, "effective_chat", None)
    return getattr(chat, "id", None)


def _safe_update_message(update):
    return getattr(update, "effective_message", None) or getattr(update, "message", None)


def _safe_exc_info(error):
    if isinstance(error, BaseException):
        return (type(error), error, error.__traceback__)
    return False


def _is_markdown_parse_error(error: BadRequest) -> bool:
    message = str(error).lower()
    return "can't parse entities" in message or "can't find end of" in message


async def _send_text(send_method, text: str, **kwargs):
    try:
        return await send_method(text, **kwargs)
    except BadRequest as error:
        if kwargs.get("parse_mode") == "Markdown" and _is_markdown_parse_error(error):
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("parse_mode", None)
            logger.warning("Telegram Markdown rejected; retrying message as plain text.")
            return await send_method(text, **fallback_kwargs)
        raise


async def _reply_text(update: Update, text: str, **kwargs):
    return await _send_text(update.message.reply_text, text, **kwargs)


async def _edit_text(message, text: str, **kwargs):
    return await _send_text(message.edit_text, text, **kwargs)


async def telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = getattr(context, "error", None)
    error_type = type(error).__name__ if error else "UnknownError"
    logger.error("Unhandled Telegram update error: %s", error_type, exc_info=_safe_exc_info(error))
    decision = ActionDecision(
        status=ActionStatus.DENIED,
        reason="Unhandled Telegram update error.",
        action=HermesAction(
            name="telegram_handler_error",
            description="Captured an unhandled Telegram handler exception.",
            actor_user_id=_safe_update_user_id(update),
            chat_id=_safe_update_chat_id(update),
            risk=ActionRisk.READ_ONLY,
            params={
                "error_type": error_type,
                "update_type": type(update).__name__ if update is not None else "None",
            },
        ),
    )
    await record_decision(decision, status="handler_error")
    message = _safe_update_message(update)
    if message:
        try:
            await message.reply_text("⚠️ Gray hit an internal error. The incident has been logged for admins.")
        except Exception as reply_error:
            logger.warning("Failed to send Telegram error reply: %s", type(reply_error).__name__)


async def _memory_worker():
    while True:
        user_id, user_message, assistant_reply = await _memory_queue.get()
        try:
            await extract_and_save(user_id, user_message, assistant_reply)
            await maybe_summarize(user_id)
        except Exception as e:
            logger.warning(f"Background extraction failed for {user_id}: {e}")
        finally:
            _memory_queue.task_done()


async def post_init(app):
    global _memory_queue, _memory_workers, _hermes_scheduler
    _memory_queue = asyncio.Queue(maxsize=MEMORY_QUEUE_SIZE)
    _memory_workers = [
        asyncio.create_task(_memory_worker())
        for _ in range(MEMORY_WORKERS)
    ]
    _hermes_scheduler = HermesScheduler(app)
    _hermes_scheduler.start()
    logger.info("Memory queue started workers=%s", MEMORY_WORKERS)
    if ALLOWED_USERS:
        logger.info("Allowlist active: %s", _role_count_summary(ALLOWED_USERS))
    else:
        logger.warning("No ALLOWED_USERS set — bot is open to everyone")
    if ADMIN_USERS:
        logger.info("Admin role active: %s", _role_count_summary(ADMIN_USERS))
    else:
        logger.warning("No ADMIN_USERS set — Hermes admin commands are unavailable")
    if OPERATOR_USERS:
        logger.info("Operator role active: %s", _role_count_summary(OPERATOR_USERS))
    logger.info(
        "Rate limit active: %s messages per %ss",
        RATE_LIMIT_MESSAGES,
        RATE_LIMIT_WINDOW_SECONDS,
    )


async def post_shutdown(app):
    global _hermes_scheduler
    if _hermes_scheduler:
        await _hermes_scheduler.stop()
        _hermes_scheduler = None
    for task in _memory_workers:
        task.cancel()
    if _memory_workers:
        await asyncio.gather(*_memory_workers, return_exceptions=True)
    await close_model_client()
    await close_embedding_client()
    await close_db_pool()


# ── Helpers ──────────────────────────────────────────────────────

async def _stream_reply(update: Update, tool_status, stream) -> str:
    placeholder = tool_status if tool_status else "Loading..."
    sent = await update.message.reply_text(placeholder)
    full_reply = ""
    last_edit = time.monotonic() if not tool_status else 0.0

    async for chunk in stream:
        full_reply += chunk
        now = time.monotonic()
        if now - last_edit >= EDIT_INTERVAL and len(full_reply) >= EDIT_MIN_CHARS:
            try:
                await sent.edit_text(full_reply)
                last_edit = now
            except Exception:
                pass

    if full_reply:
        try:
            await sent.edit_text(full_reply)
        except Exception:
            pass
    elif not tool_status:
        await sent.edit_text("⚠️ No response received.")

    return full_reply


async def _process_text(update: Update, user_id: int, text: str):
    """Core pipeline: context → route → agent → stream → save memory."""
    await update.message.chat.send_action("typing")
    history = await get_conversation_history(user_id, limit=HISTORY_LIMIT)
    memory = await get_user_memory(user_id)
    summary_ctx = await get_summary_context(user_id)
    await save_message(user_id, "user", text)

    tool_status, stream = await run_agent(text, history, memory, summary_ctx)
    full_reply = await _stream_reply(update, tool_status, stream)

    if full_reply:
        await save_message(user_id, "assistant", full_reply)
        try:
            _memory_queue.put_nowait((user_id, text, full_reply))
        except asyncio.QueueFull:
            logger.warning("Memory queue full for %s", user_id)
    return full_reply


# ── Commands ─────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "👋 Hi! I'm the Aggasys AI second brain.\n\n"
        "*What I can do:*\n"
        "• Answer using company knowledge — automatically\n"
        "• Learn from every conversation (clients, decisions, procedures)\n"
        "• Transcribe voice notes and ingest documents\n"
        "• Fetch and reason over web pages you share\n\n"
        "*Commands:*\n"
        "/start — show this message\n"
        "/task <text> — add a task or reminder\n"
        "/tasks — show open tasks\n"
        "/done <id> — mark a task complete\n"
        "/brief — morning briefing: tasks, notes, recent learning\n"
        "/standup_start <names> — open a Hermes standup workflow\n"
        "/standup_update <text> — add your standup update\n"
        "/standup_status — show standup progress\n"
        "/standup_chase — remind missing standup participants\n"
        "/standup_close — close and summarize standup\n"
        "/standup_schedule <HH:MM> <names> — schedule daily standup prompt\n"
        "/standup_chase_schedule <HH:MM> — schedule daily standup chasing\n"
        "/standup_summary_schedule <HH:MM> [chat|admins|both] — schedule daily standup summary\n"
        "/monitor_schedule <HH:MM> <query> — schedule daily web monitoring\n"
        "/schedules — list Hermes schedules\n"
        "/schedule_pause <id> — pause a Hermes schedule\n"
        "/schedule_resume <id> — resume a paused Hermes schedule\n"
        "/schedule_remove <id> — remove a Hermes schedule\n"
        "/hermes — show recent Hermes audit entries\n"
        "/hermes_status — show Hermes scheduler health\n"
        "/ops_status — show admin runtime and safety status\n"
        "/approvals — show pending Hermes approvals\n"
        "/approve <id> — approve a pending Hermes action\n"
        "/deny <id> [reason] — deny a pending Hermes action\n"
        "/note <text> — quick capture\n"
        "/recall [query] — search everything you've captured\n"
        "/memory — what I remember about you\n"
        "/wiki — list company wiki pages\n"
        "/ingest <text or url> — add to company wiki\n"
        "/lint — audit wiki for gaps\n"
        "/clear — clear conversation history\n"
        "/forget_me — delete your stored personal data\n"
        "/help — this message"
    )


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await clear_conversation(update.effective_user.id)
    await update.message.reply_text("✅ Conversation history cleared.")


def _user_data_counts_lines(counts: dict) -> list[str]:
    return [
        f"Conversations: {counts.get('conversations', 0)}",
        f"Summaries: {counts.get('summaries', 0)}",
        f"Memory facts: {counts.get('memory_facts', 0)}",
        f"Tasks: {counts.get('tasks', 0)}",
        f"Notes: {counts.get('notes', 0)}",
        f"Company-memory source links to anonymize: {counts.get('company_memory_source_links', 0)}",
    ]


async def forget_me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_private_chat(update, "forget_me"):
        return
    user_id = update.effective_user.id
    confirmed = context.args == ["CONFIRM"]
    if not confirmed:
        counts = await get_user_data_counts(user_id)
        await _reply_text(
            update,
            "This will delete your personal Gray data and anonymize company-memory source links.\n\n"
            + "\n".join(_user_data_counts_lines(counts))
            + "\n\nRun `/forget_me CONFIRM` to proceed.",
            parse_mode="Markdown",
        )
        return

    deleted = await delete_user_data(user_id)
    decision = ActionDecision(
        status=ActionStatus.ALLOWED,
        reason="User explicitly confirmed self-service personal data deletion.",
        action=HermesAction(
            name="delete_data",
            description="Self-service deletion of a user's personal Gray data.",
            actor_user_id=None,
            chat_id=None,
            risk=ActionRisk.MEDIUM,
            params={
                "scope": "self_service_user_data",
                "deleted": deleted,
                "audit_identity": "anonymized_after_self_service_delete",
            },
        ),
    )
    await record_decision(decision, status="self_service_deleted")
    await update.message.reply_text(
        "✅ Your personal Gray data has been deleted.\n\n"
        + "\n".join(_user_data_counts_lines(deleted))
    )


async def wiki_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    pages = await list_pages()
    if not pages:
        await update.message.reply_text(
            "📖 Wiki is empty.\n\nForward a document or use /ingest <text or url>."
        )
        return
    lines = ["📖 *Company Wiki*\n"]
    for p in pages:
        lines.append(f"• `{p['path']}` — {p['title']}")
    await _reply_text(update, "\n".join(lines), parse_mode="Markdown")


async def ingest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ingest text OR a URL into the wiki."""
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    arg = " ".join(context.args).strip()
    if not arg:
        await update.message.reply_text("Usage: /ingest <text or URL>")
        return

    msg = await update.message.reply_text("⚙️ Processing...")

    # Check if it's a URL
    from url_ingester import extract_urls, fetch_url_text
    urls = extract_urls(arg)
    if urls and len(arg.split()) == 1:
        url = urls[0]
        await msg.edit_text(f"🌐 Fetching {url}...")
        title, text = await fetch_url_text(url)
        if not text:
            await msg.edit_text("⚠️ Could not fetch that URL.")
            return
        ingest_text = f"Source URL: {url}\nTitle: {title}\n\n{text}"
        source_name = url
    else:
        ingest_text = arg
        source_name = f"manual_{update.effective_user.id}"

    await msg.edit_text("⚙️ Compiling into wiki...")
    updated = await ingest_document(ingest_text, source_name)
    if updated:
        await msg.edit_text("✅ Wiki updated:\n" + "\n".join(f"• {p}" for p in updated))
    else:
        await msg.edit_text("⚠️ Could not extract structured wiki pages from that content.")


async def lint_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    msg = await update.message.reply_text("🔍 Auditing wiki...")
    result = await lint_wiki()
    await _edit_text(msg, f"📋 *Wiki Audit*\n\n{result}", parse_mode="Markdown")


async def note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /note <your note>")
        return
    user_id = update.effective_user.id
    emb = None
    try:
        emb = await embed_text(text)
    except Exception:
        pass
    await save_note(user_id, text, embedding=emb)
    await update.message.reply_text("📝 Note saved.")


async def recall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified recall — searches notes, company memory, and wiki."""
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_private_chat(update, "recall"):
        return
    user_id = update.effective_user.id
    query = " ".join(context.args).strip()

    if not query:
        # No query — show recent notes only
        notes = await get_recent_notes(user_id, limit=8)
        if not notes:
            await update.message.reply_text("📓 No notes yet. Use /note to capture something.")
            return
        lines = ["📓 *Recent notes:*\n"]
        for n in notes:
            date = n["created_at"].strftime("%d %b %H:%M") if n.get("created_at") else ""
            lines.append(f"• [{date}] {n['content']}")
        await _reply_text(update, "\n".join(lines), parse_mode="Markdown")
        return

    msg = await _reply_text(update, f"🔍 Searching for: _{query}_...", parse_mode="Markdown")
    lines = []

    try:
        emb = await embed_text(query)

        # Notes
        notes = await search_notes(user_id, emb, limit=3)
        if notes:
            lines.append("📓 *Notes:*")
            for n in notes:
                date = n["created_at"].strftime("%d %b") if n.get("created_at") else ""
                lines.append(f"  • [{date}] {n['content']}")

        # Company memory
        company_facts = await semantic_search_company_memory(emb, limit=4)
        if company_facts:
            lines.append("\n🏢 *Company knowledge:*")
            for f in company_facts:
                lines.append(f"  • {f}")

        # Wiki
        wiki_results = await search_wiki(query, limit=2)
        if wiki_results:
            lines.append("\n📖 *Wiki pages:*")
            for p in wiki_results:
                snippet = p["content"][:200].replace("\n", " ")
                lines.append(f"  • *{p['title']}* — {snippet}...")

    except Exception as e:
        logger.warning(f"Recall failed: {e}")
        # Fallback to text search
        facts = await text_search_company_memory(query, limit=4)
        if facts:
            lines.append("🏢 *Company knowledge:*")
            for f in facts:
                lines.append(f"  • {f}")

    if not lines:
        await _edit_text(msg, f"🔍 Nothing found for: _{query}_", parse_mode="Markdown")
        return

    await _edit_text(msg, "\n".join(lines), parse_mode="Markdown")


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_private_chat(update, "memory"):
        return
    facts = await get_user_memory(update.effective_user.id)
    if not facts:
        await update.message.reply_text("🧠 No memories yet — they build up over time.")
        return
    lines = ["🧠 *What I remember about you:*\n"] + [f"• {f}" for f in facts]
    await _reply_text(update, "\n".join(lines), parse_mode="Markdown")


async def task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/task <text> — add an action item."""
    if not _is_allowed(update.effective_user.id):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /task <what needs doing>\n\nExample: /task Call ABC client re: renewal by Friday")
        return
    # Simple due-date extraction: look for "by <day/date>" pattern
    import re as _re
    due_match = _re.search(r'\b(?:by|before|on|due)\s+([\w\s]+?)(?:\s*$|[,.])', text, _re.IGNORECASE)
    due_text = due_match.group(1).strip() if due_match else None

    task_id = await save_task(update.effective_user.id, text, due_text)
    reply = f"✅ Task #{task_id} added."
    if due_text:
        reply += f"\n📅 Due: {due_text}"
    await update.message.reply_text(reply)


async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tasks — show open tasks."""
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_private_chat(update, "tasks"):
        return
    tasks = await get_open_tasks(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("✅ No open tasks. Add one with /task <text>")
        return
    lines = ["📋 *Open tasks:*\n"]
    for t in tasks:
        due = f" _(due: {t['due_text']})_" if t.get("due_text") else ""
        lines.append(f"• `#{t['id']}` {t['content']}{due}")
    lines.append("\nUse /done <id> to complete a task.")
    await _reply_text(update, "\n".join(lines), parse_mode="Markdown")


async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/done <id> — mark a task complete."""
    if not _is_allowed(update.effective_user.id):
        return
    args = context.args
    if not args or not args[0].isdigit():
        tasks = await get_open_tasks(update.effective_user.id)
        if not tasks:
            await update.message.reply_text("No open tasks.")
            return
        lines = ["Which task? Use /done <id>\n\n*Open tasks:*"]
        for t in tasks:
            lines.append(f"• `#{t['id']}` {t['content']}")
        await _reply_text(update, "\n".join(lines), parse_mode="Markdown")
        return

    task_id = int(args[0])
    success = await complete_task(update.effective_user.id, task_id)
    if success:
        await update.message.reply_text(f"✅ Task #{task_id} marked complete.")
    else:
        await update.message.reply_text(f"⚠️ Task #{task_id} not found or already done.")


async def brief_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/brief — morning briefing: open tasks + recent notes + conversation summary."""
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_private_chat(update, "brief"):
        return
    user_id = update.effective_user.id
    msg = await update.message.reply_text("📊 Building your briefing...")

    lines = ["📊 *Daily Brief*\n"]

    # Open tasks
    tasks = await get_open_tasks(user_id)
    if tasks:
        lines.append(f"*📋 Tasks ({len(tasks)} open):*")
        for t in tasks[:8]:
            due = f" _(due: {t['due_text']})_" if t.get("due_text") else ""
            lines.append(f"• `#{t['id']}` {t['content']}{due}")
    else:
        lines.append("*📋 Tasks:* None open")

    lines.append("")

    # Recent notes (last 5)
    notes = await get_recent_notes(user_id, limit=5)
    if notes:
        lines.append("*📓 Recent notes:*")
        for n in notes:
            date = n["created_at"].strftime("%d %b %H:%M") if n.get("created_at") else ""
            lines.append(f"• [{date}] {n['content']}")
    else:
        lines.append("*📓 Notes:* None yet")

    lines.append("")

    # Conversation summary if available
    summary = await get_summary_context(user_id)
    if summary:
        lines.append("*🧠 Earlier context:*")
        # Strip the header prefix from summary context
        summary_text = summary.replace("[Earlier conversation summary]\n", "")
        lines.append(summary_text[:400])

    await _edit_text(msg, "\n".join(lines), parse_mode="Markdown")


def _jsonb_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _normalize_daily_schedule_value(daily_at) -> str:
    return daily_at.strftime("%H:%M")


def _schedule_values_match(left: str, right: str) -> bool:
    try:
        left = _normalize_daily_schedule_value(parse_daily_time(left))
        right = _normalize_daily_schedule_value(parse_daily_time(right))
    except ValueError:
        left = left.strip()
        right = right.strip()
    return left == right


def _matching_active_schedule(jobs: list[dict], job_type: str, schedule_value: str) -> dict | None:
    for job in jobs:
        if job.get("status") != "active":
            continue
        if job.get("job_type") != job_type:
            continue
        if job.get("schedule_kind") != "daily":
            continue
        if _schedule_values_match(str(job.get("schedule_value") or ""), schedule_value):
            return job
    return None


def _display_name(update: Update) -> str:
    user = update.effective_user
    if user.username:
        return user.username
    full_name = " ".join(p for p in [user.first_name, user.last_name] if p)
    return full_name or str(user.id)


async def _decide_and_audit(update: Update, name: str, description: str,
                            risk: ActionRisk, params: dict | None = None):
    action = HermesAction(
        name=name,
        description=description,
        actor_user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        risk=risk,
        params=params or {},
    )
    decision = _hermes_policy.decide(action)
    await record_decision(decision)
    return decision


async def _request_confirmation_if_needed(update: Update, decision) -> bool:
    if not decision.needs_confirmation:
        return False
    approval_id = await create_approval_from_decision(decision)
    await _reply_text(
        update,
        f"{decision.confirmation_prompt}\n\n"
        f"Approval request: `#{approval_id}`\n"
        f"Use /approve {approval_id} or /deny {approval_id} <reason>.",
        parse_mode="Markdown",
    )
    return True


async def hermes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    rows = await get_recent_hermes_audit(update.effective_chat.id, limit=8)
    if not rows:
        await update.message.reply_text("Hermes is active. No audit entries for this chat yet.")
        return
    lines = ["*Hermes audit:*"]
    for row in rows:
        created = row["created_at"].strftime("%d %b %H:%M") if row.get("created_at") else ""
        lines.append(
            f"• `{row['action_name']}` — {row['decision']} / {row['status']} "
            f"_{created}_"
        )
    await _reply_text(update, "\n".join(lines), parse_mode="Markdown")


async def hermes_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await _decide_and_audit(
        update,
        "hermes_status",
        "Read Hermes scheduler health.",
        ActionRisk.READ_ONLY,
    )
    health = await get_hermes_scheduler_health()
    approvals = await get_hermes_approval_counts(update.effective_chat.id)
    scheduler_state = "running" if _hermes_scheduler and _hermes_scheduler.is_running else "stopped"
    next_run = health["next_run_at"].strftime("%d %b %H:%M") if health.get("next_run_at") else "none"
    lines = [
        "*Hermes status:*",
        f"Scheduler: `{scheduler_state}`",
        f"Active jobs: `{health['active_jobs']}`",
        f"Paused jobs: `{health['paused_jobs']}`",
        f"Due jobs: `{health['due_jobs']}`",
        f"Errored jobs: `{health['errored_jobs']}`",
        f"Next run: `{next_run}`",
        f"Pending approvals: `{approvals['pending']}`",
        f"Expired approvals: `{approvals['expired']}`",
    ]
    await _reply_text(update, "\n".join(lines), parse_mode="Markdown")


def _configured_state(value: str | None) -> str:
    return "set" if value else "unset"


async def ops_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    await _decide_and_audit(
        update,
        "ops_status",
        "Read redacted operational runtime and safety status.",
        ActionRisk.READ_ONLY,
    )
    health = await get_hermes_scheduler_health()
    approvals = await get_hermes_approval_counts(update.effective_chat.id)
    scheduler_state = "running" if _hermes_scheduler and _hermes_scheduler.is_running else "stopped"
    next_run = health["next_run_at"].strftime("%d %b %H:%M") if health.get("next_run_at") else "none"
    model_provider = os.getenv("MODEL_PROVIDER", "deepseek")
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "disabled")
    lines = [
        "*Gray ops status:*",
        f"Model provider: `{model_provider}`",
        f"DeepSeek key: `{_configured_state(os.getenv('DEEPSEEK_API_KEY'))}`",
        f"DeepSeek model: `{os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash')}`",
        f"Embedding provider: `{embedding_provider}`",
        f"Vision model: `{_configured_state(os.getenv('VISION_MODEL'))}`",
        f"Group mode: `{os.getenv('HERMES_GROUP_CHAT_MODE', 'mention')}`",
        f"Bot username: `{os.getenv('GRAY_BOT_USERNAME', 'unset')}`",
        f"Allowed users: `{len(ALLOWED_USERS)}`",
        f"Admins: `{len(ADMIN_USERS)}`",
        f"Operators: `{len(OPERATOR_USERS)}`",
        f"Rate limit: `{RATE_LIMIT_MESSAGES}/{RATE_LIMIT_WINDOW_SECONDS}s`",
        f"Upload caps: `doc={_format_bytes(MAX_DOCUMENT_BYTES)}, voice={_format_bytes(MAX_VOICE_BYTES)}, photo={_format_bytes(MAX_PHOTO_BYTES)}`",
        f"Memory workers: `{MEMORY_WORKERS}`",
        f"Memory queue: `{MEMORY_QUEUE_SIZE}`",
        f"Backup retention days: `{os.getenv('HERMES_BACKUP_RETENTION_DAYS', 'unset')}`",
        f"Scheduler: `{scheduler_state}`",
        f"Active jobs: `{health['active_jobs']}`",
        f"Paused jobs: `{health['paused_jobs']}`",
        f"Due jobs: `{health['due_jobs']}`",
        f"Errored jobs: `{health['errored_jobs']}`",
        f"Next run: `{next_run}`",
        f"Pending approvals: `{approvals['pending']}`",
        f"Expired approvals: `{approvals['expired']}`",
    ]
    await _reply_text(update, "\n".join(lines), parse_mode="Markdown")


async def approvals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    rows = await get_pending_hermes_approvals(update.effective_chat.id, limit=10)
    if not rows:
        await update.message.reply_text("No pending Hermes approvals.")
        return
    lines = ["*Pending Hermes approvals:*"]
    for row in rows:
        lines.append(approval_summary(row))
    lines.append("\nUse /approve <id> or /deny <id> <reason>.")
    await _reply_text(update, "\n\n".join(lines), parse_mode="Markdown")


async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /approve <approval_id>")
        return
    approval_id = int(context.args[0])
    row = await resolve_hermes_approval(
        approval_id,
        update.effective_chat.id,
        update.effective_user.id,
        "approved",
    )
    if not row:
        existing = await get_hermes_approval(approval_id, update.effective_chat.id)
        if existing and existing.get("status") == "expired":
            await update.message.reply_text(f"Approval #{approval_id} has expired. Create a fresh request.")
        else:
            await update.message.reply_text(f"Approval #{approval_id} not found or already resolved.")
        return
    await _decide_and_audit(
        update,
        f"approval:{row['action_name']}",
        f"Approved Hermes action #{approval_id}.",
        ActionRisk.READ_ONLY,
        {"approval_id": approval_id, "approved_action": row["action_name"]},
    )
    await _reply_text(
        update,
        f"✅ Approved Hermes request #{approval_id}: `{row['action_name']}`",
        parse_mode="Markdown",
    )


async def deny_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /deny <approval_id> [reason]")
        return
    approval_id = int(context.args[0])
    note = " ".join(context.args[1:]).strip() or None
    row = await resolve_hermes_approval(
        approval_id,
        update.effective_chat.id,
        update.effective_user.id,
        "denied",
        note,
    )
    if not row:
        existing = await get_hermes_approval(approval_id, update.effective_chat.id)
        if existing and existing.get("status") == "expired":
            await update.message.reply_text(f"Approval #{approval_id} has already expired.")
        else:
            await update.message.reply_text(f"Approval #{approval_id} not found or already resolved.")
        return
    await _decide_and_audit(
        update,
        f"denial:{row['action_name']}",
        f"Denied Hermes action #{approval_id}.",
        ActionRisk.READ_ONLY,
        {"approval_id": approval_id, "denied_action": row["action_name"], "reason": note},
    )
    suffix = f"\nReason: {note}" if note else ""
    await _reply_text(
        update,
        f"⛔ Denied Hermes request #{approval_id}: `{row['action_name']}`{suffix}",
        parse_mode="Markdown",
    )


async def standup_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_operator(update):
        return
    raw = " ".join(context.args).strip()
    participants = parse_participants(raw)
    if not participants:
        await update.message.reply_text("Usage: /standup_start Alice, Bob, Charlie")
        return
    decision = await _decide_and_audit(
        update,
        "standup_start",
        "Open an internal standup workflow in this chat.",
        ActionRisk.LOW,
        {"participants": participants},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this standup: {decision.reason}")
        return
    existing = await get_open_standup_session(update.effective_chat.id)
    if existing:
        await update.message.reply_text("A standup is already open. Use /standup_status or /standup_close.")
        return
    session_id = await create_standup_session(
        update.effective_chat.id,
        update.effective_user.id,
        participants,
    )
    await update.message.reply_text(
        f"✅ Standup #{session_id} opened.\n"
        "Team, post updates with /standup_update <yesterday / today / blockers>."
    )


async def standup_update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /standup_update shipped X, today Y, blocked by Z")
        return
    decision = await _decide_and_audit(
        update,
        "standup_update",
        "Record a team member standup update.",
        ActionRisk.LOW,
        {"prompt": text},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this update: {decision.reason}")
        return
    session = await save_standup_update(update.effective_chat.id, _display_name(update), text)
    if not session:
        await update.message.reply_text("No open standup. Start one with /standup_start <names>.")
        return
    await update.message.reply_text("✅ Standup update recorded.")


async def standup_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await _decide_and_audit(
        update,
        "standup_status",
        "Read current standup workflow status.",
        ActionRisk.READ_ONLY,
    )
    session = await get_open_standup_session(update.effective_chat.id)
    if not session:
        await update.message.reply_text("No open standup.")
        return
    updates = _jsonb_dict(session.get("updates"))
    participants = list(session.get("participants") or [])
    missing = missing_standup_participants(participants, updates)
    await update.message.reply_text(
        summarize_standup_updates(updates, missing)
    )


async def standup_chase_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_operator(update):
        return
    decision = await _decide_and_audit(
        update,
        "standup_chase",
        "Remind missing standup participants in the current chat.",
        ActionRisk.LOW,
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this chase: {decision.reason}")
        return
    session = await get_open_standup_session(update.effective_chat.id)
    if not session:
        await update.message.reply_text("No open standup.")
        return
    updates = _jsonb_dict(session.get("updates"))
    participants = list(session.get("participants") or [])
    missing = missing_standup_participants(participants, updates)
    await update.message.reply_text(standup_chase_message(missing))


async def standup_close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_operator(update):
        return
    decision = await _decide_and_audit(
        update,
        "standup_close",
        "Close and summarize the current standup workflow.",
        ActionRisk.LOW,
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this close: {decision.reason}")
        return
    session = await get_open_standup_session(update.effective_chat.id)
    if not session:
        await update.message.reply_text("No open standup.")
        return
    updates = _jsonb_dict(session.get("updates"))
    participants = list(session.get("participants") or [])
    missing = missing_standup_participants(participants, updates)
    summary = summarize_standup_updates(updates, missing)
    await close_standup_session(update.effective_chat.id, summary)
    await update.message.reply_text(summary)


async def standup_schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_operator(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /standup_schedule <HH:MM> Alice, Bob, Charlie")
        return
    schedule_value = context.args[0]
    raw_participants = " ".join(context.args[1:])
    try:
        daily_at = parse_daily_time(schedule_value)
    except ValueError as exc:
        await update.message.reply_text(f"Invalid time: {exc}")
        return
    schedule_value = _normalize_daily_schedule_value(daily_at)
    participants = parse_participants(raw_participants)
    if not participants:
        await update.message.reply_text("Add at least one participant.")
        return
    decision = await _decide_and_audit(
        update,
        "schedule_daily_standup",
        "Create a recurring daily standup prompt.",
        ActionRisk.LOW,
        {"participants": participants, "schedule_value": schedule_value},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this schedule: {decision.reason}")
        return
    existing_job = _matching_active_schedule(
        await get_hermes_jobs(update.effective_chat.id, limit=100),
        "daily_standup",
        schedule_value,
    )
    if existing_job:
        await update.message.reply_text(
            f"Daily standup schedule already exists as #{existing_job['id']} for {schedule_value}."
        )
        return
    next_run_at = next_daily_run(datetime_now(), daily_at)
    job_id = await create_hermes_job(
        update.effective_chat.id,
        update.effective_user.id,
        "daily_standup",
        "daily",
        schedule_value,
        next_run_at,
        {"participants": participants},
    )
    await update.message.reply_text(
        f"✅ Daily standup schedule #{job_id} created for {schedule_value}.\n"
        f"Next prompt: {next_run_at.strftime('%d %b %H:%M')}."
    )


async def standup_chase_schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_operator(update):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /standup_chase_schedule <HH:MM>")
        return
    schedule_value = context.args[0]
    try:
        daily_at = parse_daily_time(schedule_value)
    except ValueError as exc:
        await update.message.reply_text(f"Invalid time: {exc}")
        return
    schedule_value = _normalize_daily_schedule_value(daily_at)
    decision = await _decide_and_audit(
        update,
        "schedule_standup_chase",
        "Create a recurring daily standup chase reminder.",
        ActionRisk.LOW,
        {"schedule_value": schedule_value},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this chase schedule: {decision.reason}")
        return
    existing_job = _matching_active_schedule(
        await get_hermes_jobs(update.effective_chat.id, limit=100),
        "standup_chase",
        schedule_value,
    )
    if existing_job:
        await update.message.reply_text(
            f"Daily standup chase schedule already exists as #{existing_job['id']} for {schedule_value}."
        )
        return
    next_run_at = next_daily_run(datetime_now(), daily_at)
    job_id = await create_hermes_job(
        update.effective_chat.id,
        update.effective_user.id,
        "standup_chase",
        "daily",
        schedule_value,
        next_run_at,
        {},
    )
    await update.message.reply_text(
        f"✅ Daily standup chase schedule #{job_id} created for {schedule_value}.\n"
        f"Next chase: {next_run_at.strftime('%d %b %H:%M')}."
    )


async def standup_summary_schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_operator(update):
        return
    if not context.args or len(context.args) > 2:
        await update.message.reply_text("Usage: /standup_summary_schedule <HH:MM> [chat|admins|both]")
        return
    schedule_value = context.args[0]
    raw_recipient_tier = context.args[1].strip().lower() if len(context.args) == 2 else "chat"
    if raw_recipient_tier not in SUMMARY_RECIPIENT_TIERS:
        await update.message.reply_text("Invalid recipient tier. Use one of: chat, admins, both.")
        return
    recipient_tier = summary_recipient_tier(raw_recipient_tier)
    try:
        daily_at = parse_daily_time(schedule_value)
    except ValueError as exc:
        await update.message.reply_text(f"Invalid time: {exc}")
        return
    schedule_value = _normalize_daily_schedule_value(daily_at)
    decision = await _decide_and_audit(
        update,
        "schedule_standup_summary",
        "Create a recurring daily standup close-and-summary job.",
        ActionRisk.LOW,
        {"schedule_value": schedule_value, "summary_recipients": recipient_tier},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this summary schedule: {decision.reason}")
        return
    existing_job = _matching_active_schedule(
        await get_hermes_jobs(update.effective_chat.id, limit=100),
        "standup_summary",
        schedule_value,
    )
    if existing_job:
        await update.message.reply_text(
            f"Daily standup summary schedule already exists as #{existing_job['id']} for {schedule_value}."
        )
        return
    next_run_at = next_daily_run(datetime_now(), daily_at)
    job_id = await create_hermes_job(
        update.effective_chat.id,
        update.effective_user.id,
        "standup_summary",
        "daily",
        schedule_value,
        next_run_at,
        {"summary_recipients": recipient_tier},
    )
    await update.message.reply_text(
        f"✅ Daily standup summary schedule #{job_id} created for {schedule_value}.\n"
        f"Recipients: {recipient_tier}.\n"
        f"Next summary: {next_run_at.strftime('%d %b %H:%M')}."
    )


async def monitor_schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /monitor_schedule <HH:MM> <query>")
        return
    schedule_value = context.args[0]
    query = " ".join(context.args[1:]).strip()
    try:
        daily_at = parse_daily_time(schedule_value)
    except ValueError as exc:
        await update.message.reply_text(f"Invalid time: {exc}")
        return
    schedule_value = _normalize_daily_schedule_value(daily_at)
    decision = await _decide_and_audit(
        update,
        "schedule_web_monitor",
        "Create a recurring daily web monitor.",
        ActionRisk.LOW,
        {"schedule_value": schedule_value, "query": query},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this monitor schedule: {decision.reason}")
        return
    existing_job = _matching_active_schedule(
        await get_hermes_jobs(update.effective_chat.id, limit=100),
        "web_monitor",
        schedule_value,
    )
    if existing_job:
        await update.message.reply_text(
            f"Daily web monitor schedule already exists as #{existing_job['id']} for {schedule_value}."
        )
        return
    next_run_at = next_daily_run(datetime_now(), daily_at)
    job_id = await create_hermes_job(
        update.effective_chat.id,
        update.effective_user.id,
        "web_monitor",
        "daily",
        schedule_value,
        next_run_at,
        {"query": query},
    )
    await update.message.reply_text(
        f"✅ Daily web monitor #{job_id} created for {schedule_value}.\n"
        f"Query: {query}\n"
        f"Next check: {next_run_at.strftime('%d %b %H:%M')}."
    )


async def schedules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await _decide_and_audit(
        update,
        "list_schedules",
        "Read Hermes scheduled jobs.",
        ActionRisk.READ_ONLY,
    )
    jobs = await get_hermes_jobs(update.effective_chat.id, limit=20)
    if not jobs:
        await update.message.reply_text("No Hermes schedules for this chat.")
        return
    lines = ["*Hermes schedules:*"]
    for job in jobs:
        next_run = job["next_run_at"].strftime("%d %b %H:%M") if job.get("next_run_at") else ""
        failure = ""
        if job.get("consecutive_failures"):
            failure = f" failures={job['consecutive_failures']}"
        error = ""
        if job.get("last_error"):
            error = f"\n  last error: {str(job['last_error'])[:120]}"
        lines.append(
            f"• `#{job['id']}` {job['job_type']} — {job['status']} "
            f"{job['schedule_kind']} {job['schedule_value']} next {next_run}{failure}{error}"
        )
    await _reply_text(update, "\n".join(lines), parse_mode="Markdown")


async def schedule_pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /schedule_pause <id>")
        return
    job_id = int(context.args[0])
    decision = await _decide_and_audit(
        update,
        "pause_schedule",
        f"Pause Hermes schedule #{job_id}.",
        ActionRisk.LOW,
        {"job_id": job_id},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this pause: {decision.reason}")
        return
    if await pause_hermes_job(update.effective_chat.id, job_id):
        await update.message.reply_text(f"✅ Paused Hermes schedule #{job_id}.")
    else:
        await update.message.reply_text(f"Schedule #{job_id} not found or already inactive.")


async def schedule_resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /schedule_resume <id>")
        return
    job_id = int(context.args[0])
    jobs = await get_hermes_jobs(update.effective_chat.id, limit=100)
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        await update.message.reply_text(f"Schedule #{job_id} not found.")
        return
    if job["schedule_kind"] != "daily":
        await update.message.reply_text(f"Schedule #{job_id} cannot be resumed automatically.")
        return
    decision = await _decide_and_audit(
        update,
        "resume_schedule",
        f"Resume Hermes schedule #{job_id}.",
        ActionRisk.LOW,
        {"job_id": job_id},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this resume: {decision.reason}")
        return
    try:
        daily_at = parse_daily_time(job["schedule_value"])
    except ValueError:
        await update.message.reply_text(f"Schedule #{job_id} has an invalid daily time.")
        return
    next_run_at = next_daily_run(datetime_now(), daily_at)
    if await resume_hermes_job(update.effective_chat.id, job_id, next_run_at):
        await update.message.reply_text(
            f"✅ Resumed Hermes schedule #{job_id}.\n"
            f"Next prompt: {next_run_at.strftime('%d %b %H:%M')}."
        )
    else:
        await update.message.reply_text(f"Schedule #{job_id} is not paused or could not be resumed.")


async def schedule_remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    if not await _require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /schedule_remove <id>")
        return
    job_id = int(context.args[0])
    decision = await _decide_and_audit(
        update,
        "remove_schedule",
        f"Remove Hermes schedule #{job_id}.",
        ActionRisk.LOW,
        {"job_id": job_id},
    )
    if await _request_confirmation_if_needed(update, decision):
        return
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this removal: {decision.reason}")
        return
    if await remove_hermes_job(update.effective_chat.id, job_id):
        await update.message.reply_text(f"✅ Removed Hermes schedule #{job_id}.")
    else:
        await update.message.reply_text(f"Schedule #{job_id} not found or already removed.")


def datetime_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from hermes.scheduler import HERMES_TIMEZONE

    return datetime.now(ZoneInfo(HERMES_TIMEZONE))


# ── Message handlers ─────────────────────────────────────────────

TEXT_COMMAND_HANDLERS = {
    "start": start,
    "help": start,
    "clear": clear_cmd,
    "forget_me": forget_me_cmd,
    "wiki": wiki_cmd,
    "ingest": ingest_cmd,
    "lint": lint_cmd,
    "note": note_cmd,
    "recall": recall_cmd,
    "memory": memory_cmd,
    "task": task_cmd,
    "tasks": tasks_cmd,
    "done": done_cmd,
    "brief": brief_cmd,
    "hermes": hermes_cmd,
    "hermes_status": hermes_status_cmd,
    "ops_status": ops_status_cmd,
    "approvals": approvals_cmd,
    "approve": approve_cmd,
    "deny": deny_cmd,
    "standup_start": standup_start_cmd,
    "standup_update": standup_update_cmd,
    "standup_status": standup_status_cmd,
    "standup_chase": standup_chase_cmd,
    "standup_close": standup_close_cmd,
    "standup_schedule": standup_schedule_cmd,
    "standup_chase_schedule": standup_chase_schedule_cmd,
    "standup_summary_schedule": standup_summary_schedule_cmd,
    "monitor_schedule": monitor_schedule_cmd,
    "schedules": schedules_cmd,
    "schedule_pause": schedule_pause_cmd,
    "schedule_resume": schedule_resume_cmd,
    "schedule_remove": schedule_remove_cmd,
}


async def _maybe_dispatch_text_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Handle commands that arrive as mentioned text, e.g. '@Gray /ops_status'."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False
    parts = stripped.split()
    command = parts[0][1:].split("@", 1)[0].lower()
    handler = TEXT_COMMAND_HANDLERS.get(command)
    if not handler:
        await update.message.reply_text(f"Unknown command: /{command}. Use /help for available commands.")
        return True
    previous_args = getattr(context, "args", None)
    context.args = parts[1:]
    try:
        await handler(update, context)
    finally:
        context.args = previous_args
    return True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    bot_username, bot_id = _bot_identity(context)
    if not should_process_message(update, bot_username=bot_username, bot_id=bot_id):
        return
    text = strip_bot_mention(update.message.text, bot_username)
    if await _maybe_dispatch_text_command(update, context, text):
        return
    if await _maybe_capture_standup_update(update, text):
        return
    try:
        await _process_text(update, update.effective_user.id, text)
    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


async def _maybe_capture_standup_update(update: Update, text: str) -> bool:
    if not looks_like_standup_update(text):
        return False
    session = await get_open_standup_session(update.effective_chat.id)
    if not session:
        return False
    decision = await _decide_and_audit(
        update,
        "standup_update_natural",
        "Record a natural-language standup update.",
        ActionRisk.LOW,
        {"prompt": text},
    )
    if not decision.allowed:
        await update.message.reply_text(f"Hermes blocked this standup update: {decision.reason}")
        return True
    await save_standup_update(update.effective_chat.id, _display_name(update), text)
    await update.message.reply_text("✅ Standup update recorded.")
    return True


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    bot_username, bot_id = _bot_identity(context)
    if not should_process_message(update, bot_username=bot_username, bot_id=bot_id):
        return
    voice = update.message.voice
    if await _reject_oversize_upload(update, "voice", getattr(voice, "file_size", None), MAX_VOICE_BYTES):
        return
    msg = await update.message.reply_text("🎙️ Transcribing...")
    text = None
    try:
        from voice import transcribe
        voice_file = await voice.get_file()
        audio_bytes = bytes(await voice_file.download_as_bytearray())
        text = await transcribe(audio_bytes, mime_type="audio/ogg")
    except Exception as e:
        logger.error(f"Voice transcription error: {e}")

    if not text:
        await msg.edit_text(
            "⚠️ Could not transcribe voice message.\n"
            "Make sure WHISPER_MODEL is set and ffmpeg is installed."
        )
        return

    await _edit_text(msg, f"🎙️ _{text}_", parse_mode="Markdown")
    try:
        await _process_text(update, update.effective_user.id, text)
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await update.message.reply_text("⚠️ Transcribed but couldn't generate a reply.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    bot_username, bot_id = _bot_identity(context)
    if not should_process_message(update, bot_username=bot_username, bot_id=bot_id):
        return
    doc = update.message.document
    caption = strip_bot_mention(update.message.caption or "", bot_username)
    if await _reject_oversize_upload(update, "document", getattr(doc, "file_size", None), MAX_DOCUMENT_BYTES):
        return
    msg = await _reply_text(update, f"📄 Processing *{doc.file_name}*...", parse_mode="Markdown")

    try:
        file = await doc.get_file()
        file_bytes = bytes(await file.download_as_bytearray())
        fname = doc.file_name.lower()

        if fname.endswith(".pdf"):
            try:
                import io
                import pdfplumber
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    text = "\n\n".join(
                        (page.extract_text() or "").strip() for page in pdf.pages
                    ).strip()
            except ImportError:
                await msg.edit_text("⚠️ PDF support unavailable (pdfplumber not installed).")
                return
        elif fname.endswith((".txt", ".md")):
            text = file_bytes.decode("utf-8", errors="replace")
        else:
            await _edit_text(
                msg,
                f"⚠️ Unsupported: `{doc.file_name}`\n\nSupported: PDF, TXT, MD",
                parse_mode="Markdown"
            )
            return

        if not text.strip():
            await msg.edit_text("⚠️ Could not extract text from the document.")
            return

        if caption:
            text = f"Context: {caption}\n\n{text}"

        updated = await ingest_document(text, doc.file_name)
        if updated:
            await msg.edit_text("✅ Ingested into wiki:\n" + "\n".join(f"• {p}" for p in updated))
        else:
            await msg.edit_text("⚠️ Could not extract wiki pages from that document.")

    except Exception as e:
        logger.error(f"Document handling error: {e}")
        await msg.edit_text("⚠️ Failed to process document.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    bot_username, bot_id = _bot_identity(context)
    if not should_process_message(update, bot_username=bot_username, bot_id=bot_id):
        return
    caption = strip_bot_mention(update.message.caption or "", bot_username)
    vision_model = os.getenv("VISION_MODEL", "")

    if not vision_model:
        await _reply_text(
            update,
            "🖼️ Image received. Set `VISION_MODEL=llava` in .env to enable analysis.",
            parse_mode="Markdown"
        )
        return

    photo = update.message.photo[-1]
    if await _reject_oversize_upload(update, "photo", getattr(photo, "file_size", None), MAX_PHOTO_BYTES):
        return
    msg = await update.message.reply_text("🖼️ Analysing image...")
    try:
        import base64
        import httpx

        file = await photo.get_file()
        file_bytes = bytes(await file.download_as_bytearray())
        image_b64 = base64.b64encode(file_bytes).decode()
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        prompt_text = caption or "Describe this image in detail. Extract any text, data, or key information."

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": vision_model,
                    "messages": [{"role": "user", "content": prompt_text, "images": [image_b64]}],
                    "stream": False,
                }
            )
            resp.raise_for_status()
            description = resp.json()["message"]["content"]

        await _edit_text(msg, f"🖼️ *Image analysis:*\n\n{description}", parse_mode="Markdown")

        user_id = update.effective_user.id
        await save_message(user_id, "user", f"[Image{': ' + caption if caption else ''}]")
        await save_message(user_id, "assistant", description)

    except Exception as e:
        logger.error(f"Photo handling error: {e}")
        await msg.edit_text("⚠️ Could not analyse image.")


# ── App entry point ──────────────────────────────────────────────

def main():
    report = collect_preflight_report(os.environ)
    if not report.ok:
        logger.error("\n%s", render_report(report))
        raise SystemExit(1)
    for warning in report.warnings:
        logger.warning("Preflight: %s", warning)

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", _rate_limited(start)))
    app.add_handler(CommandHandler("help", _rate_limited(start)))
    app.add_handler(CommandHandler("clear", _rate_limited(clear_cmd)))
    app.add_handler(CommandHandler("forget_me", _rate_limited(forget_me_cmd)))
    app.add_handler(CommandHandler("wiki", _rate_limited(wiki_cmd)))
    app.add_handler(CommandHandler("ingest", _rate_limited(ingest_cmd)))
    app.add_handler(CommandHandler("lint", _rate_limited(lint_cmd)))
    app.add_handler(CommandHandler("note", _rate_limited(note_cmd)))
    app.add_handler(CommandHandler("recall", _rate_limited(recall_cmd)))
    app.add_handler(CommandHandler("memory", _rate_limited(memory_cmd)))
    app.add_handler(CommandHandler("task", _rate_limited(task_cmd)))
    app.add_handler(CommandHandler("tasks", _rate_limited(tasks_cmd)))
    app.add_handler(CommandHandler("done", _rate_limited(done_cmd)))
    app.add_handler(CommandHandler("brief", _rate_limited(brief_cmd)))
    app.add_handler(CommandHandler("hermes", _rate_limited(hermes_cmd)))
    app.add_handler(CommandHandler("hermes_status", _rate_limited(hermes_status_cmd)))
    app.add_handler(CommandHandler("ops_status", _rate_limited(ops_status_cmd)))
    app.add_handler(CommandHandler("approvals", _rate_limited(approvals_cmd)))
    app.add_handler(CommandHandler("approve", _rate_limited(approve_cmd)))
    app.add_handler(CommandHandler("deny", _rate_limited(deny_cmd)))
    app.add_handler(CommandHandler("standup_start", _rate_limited(standup_start_cmd)))
    app.add_handler(CommandHandler("standup_update", _rate_limited(standup_update_cmd)))
    app.add_handler(CommandHandler("standup_status", _rate_limited(standup_status_cmd)))
    app.add_handler(CommandHandler("standup_chase", _rate_limited(standup_chase_cmd)))
    app.add_handler(CommandHandler("standup_close", _rate_limited(standup_close_cmd)))
    app.add_handler(CommandHandler("standup_schedule", _rate_limited(standup_schedule_cmd)))
    app.add_handler(CommandHandler("standup_chase_schedule", _rate_limited(standup_chase_schedule_cmd)))
    app.add_handler(CommandHandler("standup_summary_schedule", _rate_limited(standup_summary_schedule_cmd)))
    app.add_handler(CommandHandler("monitor_schedule", _rate_limited(monitor_schedule_cmd)))
    app.add_handler(CommandHandler("schedules", _rate_limited(schedules_cmd)))
    app.add_handler(CommandHandler("schedule_pause", _rate_limited(schedule_pause_cmd)))
    app.add_handler(CommandHandler("schedule_resume", _rate_limited(schedule_resume_cmd)))
    app.add_handler(CommandHandler("schedule_remove", _rate_limited(schedule_remove_cmd)))
    app.add_handler(MessageHandler(filters.VOICE, _rate_limited(handle_voice)))
    app.add_handler(MessageHandler(filters.Document.ALL, _rate_limited(handle_document)))
    app.add_handler(MessageHandler(filters.PHOTO, _rate_limited(handle_photo)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _rate_limited(handle_message)))
    app.add_error_handler(telegram_error_handler)

    logger.info("Aggasys second brain starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
