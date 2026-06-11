import asyncio
import logging
import os
import time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    filters, ContextTypes
)
from agent import run_agent
from db import (
    get_conversation_history, save_message,
    get_user_memory, clear_conversation,
    save_note, get_recent_notes, search_notes,
    save_task, get_open_tasks, complete_task, get_all_tasks,
    get_conversation_count, SUMMARY_TRIGGER_MESSAGES,
)
from memory_extractor import extract_and_save
from summarizer import maybe_summarize, get_summary_context
from ollama_client import close_client as close_ollama_client
from embedding import close_client as close_embedding_client, embed_text
from wiki import list_pages, ingest_document, lint_wiki, search_wiki
from db import semantic_search_company_memory, text_search_company_memory

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "6"))
MEMORY_QUEUE_SIZE = int(os.getenv("MEMORY_QUEUE_SIZE", "100"))
MEMORY_WORKERS = int(os.getenv("MEMORY_WORKERS", "1"))

EDIT_INTERVAL = 1.2
EDIT_MIN_CHARS = 40

_ALLOWED_RAW = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = {
    int(uid.strip()) for uid in _ALLOWED_RAW.split(",") if uid.strip().isdigit()
}

_memory_queue = None
_memory_workers = []


def _is_allowed(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


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
    global _memory_queue, _memory_workers
    _memory_queue = asyncio.Queue(maxsize=MEMORY_QUEUE_SIZE)
    _memory_workers = [
        asyncio.create_task(_memory_worker())
        for _ in range(MEMORY_WORKERS)
    ]
    logger.info("Memory queue started workers=%s", MEMORY_WORKERS)
    if ALLOWED_USERS:
        logger.info("Allowlist active: %s", ALLOWED_USERS)
    else:
        logger.warning("No ALLOWED_USERS set — bot is open to everyone")


async def post_shutdown(app):
    for task in _memory_workers:
        task.cancel()
    if _memory_workers:
        await asyncio.gather(*_memory_workers, return_exceptions=True)
    await close_ollama_client()
    await close_embedding_client()


# ── Helpers ──────────────────────────────────────────────────────

async def _stream_reply(update: Update, tool_status, stream) -> str:
    placeholder = tool_status if tool_status else "..."
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
        "/task <text> — add a task or reminder\n"
        "/tasks — show open tasks\n"
        "/done <id> — mark a task complete\n"
        "/brief — morning briefing: tasks, notes, recent learning\n"
        "/note <text> — quick capture\n"
        "/recall [query] — search everything you've captured\n"
        "/memory — what I remember about you\n"
        "/wiki — list company wiki pages\n"
        "/ingest <text or url> — add to company wiki\n"
        "/lint — audit wiki for gaps\n"
        "/clear — clear conversation history\n"
        "/help — this message",
        parse_mode="Markdown"
    )


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await clear_conversation(update.effective_user.id)
    await update.message.reply_text("✅ Conversation history cleared.")


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
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def ingest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ingest text OR a URL into the wiki."""
    if not _is_allowed(update.effective_user.id):
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
    msg = await update.message.reply_text("🔍 Auditing wiki...")
    result = await lint_wiki()
    await msg.edit_text(f"📋 *Wiki Audit*\n\n{result}", parse_mode="Markdown")


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
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"🔍 Searching for: _{query}_...", parse_mode="Markdown")
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
        await msg.edit_text(f"🔍 Nothing found for: _{query}_", parse_mode="Markdown")
        return

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    facts = await get_user_memory(update.effective_user.id)
    if not facts:
        await update.message.reply_text("🧠 No memories yet — they build up over time.")
        return
    lines = ["🧠 *What I remember about you:*\n"] + [f"• {f}" for f in facts]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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
    tasks = await get_open_tasks(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("✅ No open tasks. Add one with /task <text>")
        return
    lines = ["📋 *Open tasks:*\n"]
    for t in tasks:
        due = f" _(due: {t['due_text']})_" if t.get("due_text") else ""
        lines.append(f"• `#{t['id']}` {t['content']}{due}")
    lines.append("\nUse /done <id> to complete a task.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
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

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ── Message handlers ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    try:
        await _process_text(update, update.effective_user.id, update.message.text)
    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    msg = await update.message.reply_text("🎙️ Transcribing...")
    text = None
    try:
        from voice import transcribe
        voice_file = await update.message.voice.get_file()
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

    await msg.edit_text(f"🎙️ _{text}_", parse_mode="Markdown")
    try:
        await _process_text(update, update.effective_user.id, text)
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await update.message.reply_text("⚠️ Transcribed but couldn't generate a reply.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    doc = update.message.document
    caption = update.message.caption or ""
    msg = await update.message.reply_text(f"📄 Processing *{doc.file_name}*...", parse_mode="Markdown")

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
            await msg.edit_text(
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
    caption = update.message.caption or ""
    vision_model = os.getenv("VISION_MODEL", "")

    if not vision_model:
        await update.message.reply_text(
            "🖼️ Image received. Set `VISION_MODEL=llava` in .env to enable analysis.",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text("🖼️ Analysing image...")
    try:
        import base64
        import httpx

        photo = update.message.photo[-1]
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

        await msg.edit_text(f"🖼️ *Image analysis:*\n\n{description}", parse_mode="Markdown")

        user_id = update.effective_user.id
        await save_message(user_id, "user", f"[Image{': ' + caption if caption else ''}]")
        await save_message(user_id, "assistant", description)

    except Exception as e:
        logger.error(f"Photo handling error: {e}")
        await msg.edit_text("⚠️ Could not analyse image.")


# ── App entry point ──────────────────────────────────────────────

def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("wiki", wiki_cmd))
    app.add_handler(CommandHandler("ingest", ingest_cmd))
    app.add_handler(CommandHandler("lint", lint_cmd))
    app.add_handler(CommandHandler("note", note_cmd))
    app.add_handler(CommandHandler("recall", recall_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("task", task_cmd))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("brief", brief_cmd))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Aggasys second brain starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
