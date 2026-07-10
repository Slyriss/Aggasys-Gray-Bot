import os
import sys
import unittest
import types
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

telegram = types.ModuleType("telegram")
telegram.Update = object
telegram_ext = types.ModuleType("telegram.ext")
telegram_ext.ApplicationBuilder = object
telegram_ext.MessageHandler = object
telegram_ext.CommandHandler = object
telegram_ext.filters = SimpleNamespace(VOICE=object(), Document=SimpleNamespace(ALL=object()), PHOTO=object(), TEXT=object(), COMMAND=object())
telegram_ext.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
sys.modules.setdefault("telegram", telegram)
sys.modules.setdefault("telegram.ext", telegram_ext)

dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault("dotenv", dotenv)

agent = types.ModuleType("agent")
agent.run_agent = AsyncMock()
sys.modules.setdefault("agent", agent)

db = types.ModuleType("db")
for name in [
    "get_conversation_history", "save_message", "get_user_memory", "clear_conversation",
    "save_note", "get_recent_notes", "search_notes", "save_task", "get_open_tasks",
    "complete_task", "get_all_tasks", "get_conversation_count", "create_standup_session",
    "get_open_standup_session", "save_standup_update", "close_standup_session",
    "get_recent_hermes_audit", "get_pending_hermes_approvals", "resolve_hermes_approval",
    "create_hermes_job", "get_hermes_jobs", "pause_hermes_job", "remove_hermes_job",
    "resume_hermes_job", "get_hermes_approval", "get_hermes_approval_counts",
    "get_hermes_scheduler_health", "semantic_search_company_memory",
    "text_search_company_memory",
]:
    setattr(db, name, AsyncMock())
db.SUMMARY_TRIGGER_MESSAGES = 20
sys.modules.setdefault("db", db)

for module_name in ["memory_extractor", "summarizer", "model_client", "embedding", "wiki"]:
    module = types.ModuleType(module_name)
    sys.modules.setdefault(module_name, module)

sys.modules["memory_extractor"].extract_and_save = AsyncMock()
sys.modules["summarizer"].maybe_summarize = AsyncMock()
sys.modules["summarizer"].get_summary_context = AsyncMock(return_value="")
sys.modules["model_client"].close_client = AsyncMock()
sys.modules["embedding"].close_client = AsyncMock()
sys.modules["embedding"].embed_text = AsyncMock(return_value=[])
sys.modules["wiki"].list_pages = AsyncMock(return_value=[])
sys.modules["wiki"].ingest_document = AsyncMock()
sys.modules["wiki"].lint_wiki = AsyncMock(return_value=[])
sys.modules["wiki"].search_wiki = AsyncMock(return_value=[])

import main as bot_main
from hermes import ActionDecision, ActionRisk, ActionStatus, HermesAction


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


def fake_update(user_id=123, chat_id=-100):
    message = FakeMessage()
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username="alice", first_name="Alice", last_name=None),
        effective_chat=SimpleNamespace(id=chat_id, type="group"),
        message=message,
    )


def allowed_decision(name="test", params=None):
    return ActionDecision(
        status=ActionStatus.ALLOWED,
        reason="allowed",
        action=HermesAction(name=name, description=name, risk=ActionRisk.LOW, params=params or {}),
    )


class BotScheduleCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_standup_schedule_creates_daily_standup_job(self):
        update = fake_update()
        context = SimpleNamespace(args=["09:30", "Alice,", "Bob"])

        with patch.object(bot_main, "_decide_and_audit", AsyncMock(return_value=allowed_decision())), \
             patch.object(bot_main, "datetime_now", return_value=datetime(2026, 7, 9, 8, 0)), \
             patch.object(bot_main, "create_hermes_job", AsyncMock(return_value=41)) as create_job:
            await bot_main.standup_schedule_cmd(update, context)

        create_job.assert_awaited_once()
        args = create_job.await_args.args
        self.assertEqual(args[2], "daily_standup")
        self.assertEqual(args[3], "daily")
        self.assertEqual(args[4], "09:30")
        self.assertEqual(args[6], {"participants": ["Alice", "Bob"]})
        self.assertIn("Daily standup schedule #41", update.message.replies[0]["text"])

    async def test_standup_chase_schedule_creates_chase_job(self):
        update = fake_update()
        context = SimpleNamespace(args=["09:50"])

        with patch.object(bot_main, "_decide_and_audit", AsyncMock(return_value=allowed_decision())), \
             patch.object(bot_main, "datetime_now", return_value=datetime(2026, 7, 9, 8, 0)), \
             patch.object(bot_main, "create_hermes_job", AsyncMock(return_value=42)) as create_job:
            await bot_main.standup_chase_schedule_cmd(update, context)

        create_job.assert_awaited_once()
        args = create_job.await_args.args
        self.assertEqual(args[2], "standup_chase")
        self.assertEqual(args[3], "daily")
        self.assertEqual(args[4], "09:50")
        self.assertEqual(args[6], {})
        self.assertIn("Daily standup chase schedule #42", update.message.replies[0]["text"])

    async def test_monitor_schedule_creates_web_monitor_job(self):
        update = fake_update()
        context = SimpleNamespace(args=["10:00", "Singapore", "SME", "AI", "tenders"])

        with patch.object(bot_main, "_decide_and_audit", AsyncMock(return_value=allowed_decision())), \
             patch.object(bot_main, "datetime_now", return_value=datetime(2026, 7, 9, 8, 0)), \
             patch.object(bot_main, "create_hermes_job", AsyncMock(return_value=43)) as create_job:
            await bot_main.monitor_schedule_cmd(update, context)

        create_job.assert_awaited_once()
        args = create_job.await_args.args
        self.assertEqual(args[2], "web_monitor")
        self.assertEqual(args[3], "daily")
        self.assertEqual(args[4], "10:00")
        self.assertEqual(args[6], {"query": "Singapore SME AI tenders"})
        self.assertIn("Daily web monitor #43", update.message.replies[0]["text"])

    async def test_monitor_schedule_rejects_missing_query(self):
        update = fake_update()
        context = SimpleNamespace(args=["10:00"])

        with patch.object(bot_main, "create_hermes_job", AsyncMock()) as create_job:
            await bot_main.monitor_schedule_cmd(update, context)

        create_job.assert_not_awaited()
        self.assertEqual(update.message.replies[0]["text"], "Usage: /monitor_schedule <HH:MM> <query>")


if __name__ == "__main__":
    unittest.main()
