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
    get_user_memory, clear_conversation
)
from memory_extractor import extract_and_save
from wiki import list_pages, ingest_document, lint_wiki

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Telegram allows ~1 edit per second per chat; stay safely under that
EDIT_INTERVAL = 1.2   # seconds between edits
EDIT_MIN_CHARS = 40   # don't edit until we have at least this many chars


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm the Aggasys AI assistant.\n"
        "Ask me anything — jobs, clients, IT questions, or drafting help.\n\n"
        "Commands:\n"
        "/clear — clear your conversation history\n"
        "/wiki — list all company wiki pages\n"
        "/ingest <text> — compile a document into the wiki\n"
        "/lint — audit the wiki for gaps\n"
        "/help — show this message"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await clear_conversation(user_id)
    await update.message.reply_text("✅ Conversation history cleared.")


async def wiki_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all wiki pages."""
    pages = await list_pages()
    if not pages:
        await update.message.reply_text(
            "📖 Wiki is empty.\n\nUse /ingest <text> to add your first document."
        )
        return
    lines = ["📖 *Company Wiki*\n"]
    for p in pages:
        lines.append(f"• `{p['path']}` — {p['title']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def ingest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ingest a pasted document into the wiki. Usage: /ingest <text>"""
    text = " ".join(context.args)
    if not text.strip():
        await update.message.reply_text(
            "Usage: /ingest <document text>\n\nPaste any text after /ingest and the bot will compile it into the wiki."
        )
        return
    msg = await update.message.reply_text("⚙️ Compiling into wiki...")
    source = f"manual_ingest_{update.effective_user.id}"
    updated = await ingest_document(text, source)
    if updated:
        pages_list = "\n".join(f"• {p}" for p in updated)
        await msg.edit_text(f"✅ Wiki updated:\n{pages_list}")
    else:
        await msg.edit_text("⚠️ Could not extract any wiki pages from that text.")


async def lint_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run wiki health check."""
    msg = await update.message.reply_text("🔍 Auditing wiki...")
    result = await lint_wiki()
    await msg.edit_text(f"📋 *Wiki Audit*\n\n{result}", parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_message = update.message.text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        history = await get_conversation_history(user_id, limit=10)
        memory = await get_user_memory(user_id)
        await save_message(user_id, "user", user_message)

        # Route through agent (tool detection + streaming response)
        tool_status, stream = await run_agent(user_message, history, memory)

        # Send placeholder — updated as tokens arrive
        placeholder = tool_status if tool_status else "..."
        sent = await update.message.reply_text(placeholder)

        full_reply = ""
        last_edit = time.monotonic() if not tool_status else 0.0

        async for chunk in stream:
            full_reply += chunk
            now = time.monotonic()
            if (now - last_edit >= EDIT_INTERVAL and len(full_reply) >= EDIT_MIN_CHARS):
                try:
                    await sent.edit_text(full_reply)
                    last_edit = now
                except Exception:
                    pass

        # Final edit with the complete reply
        if full_reply:
            try:
                await sent.edit_text(full_reply)
            except Exception:
                pass
        elif not tool_status:
            await sent.edit_text("⚠️ No response received.")

        if full_reply:
            await save_message(user_id, "assistant", full_reply)
            # Background fact extraction — doesn't block the reply
            asyncio.create_task(extract_and_save(user_id, user_message, full_reply))

    except Exception as e:
        logger.error(f"Error handling message from {user_name}: {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong. Please try again in a moment."
        )


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("wiki", wiki_cmd))
    app.add_handler(CommandHandler("ingest", ingest_cmd))
    app.add_handler(CommandHandler("lint", lint_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Aggasys bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
