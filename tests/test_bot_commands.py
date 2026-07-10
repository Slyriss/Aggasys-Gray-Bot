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
    "get_user_data_counts", "delete_user_data",
    "save_note", "get_recent_notes", "search_notes", "save_task", "get_open_tasks",
    "complete_task", "get_all_tasks", "get_conversation_count", "create_standup_session",
    "get_open_standup_session", "save_standup_update", "close_standup_session",
    "get_recent_hermes_audit", "get_pending_hermes_approvals", "resolve_hermes_approval",
    "create_hermes_job", "get_hermes_jobs", "pause_hermes_job", "remove_hermes_job",
    "resume_hermes_job", "get_hermes_approval", "get_hermes_approval_counts",
    "get_hermes_scheduler_health", "semantic_search_company_memory",
    "text_search_company_memory", "close_pool",
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
    async def asyncSetUp(self):
        self.role_patchers = [
            patch.object(bot_main, "ALLOWED_USERS", {123, 456, 789}),
            patch.object(bot_main, "ADMIN_USERS", {123}),
            patch.object(bot_main, "OPERATOR_USERS", {456}),
        ]
        for patcher in self.role_patchers:
            patcher.start()

    async def asyncTearDown(self):
        for patcher in reversed(self.role_patchers):
            patcher.stop()

    async def test_standup_schedule_creates_daily_standup_job(self):
        update = fake_update(user_id=456)
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
        update = fake_update(user_id=456)
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
        update = fake_update(user_id=123)
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
        update = fake_update(user_id=123)
        context = SimpleNamespace(args=["10:00"])

        with patch.object(bot_main, "create_hermes_job", AsyncMock()) as create_job:
            await bot_main.monitor_schedule_cmd(update, context)

        create_job.assert_not_awaited()
        self.assertEqual(update.message.replies[0]["text"], "Usage: /monitor_schedule <HH:MM> <query>")

    async def test_monitor_schedule_requires_admin_role(self):
        update = fake_update(user_id=456)
        context = SimpleNamespace(args=["10:00", "Singapore", "AI", "tenders"])

        with patch.object(bot_main, "create_hermes_job", AsyncMock()) as create_job, \
             patch.object(bot_main, "record_decision", AsyncMock()) as record:
            await bot_main.monitor_schedule_cmd(update, context)

        create_job.assert_not_awaited()
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "rbac_denied:admin")
        self.assertEqual(record.await_args.kwargs["status"], "blocked_rbac")
        self.assertEqual(update.message.replies[0]["text"], "Restricted to Gray admins.")

    async def test_standup_schedule_requires_operator_role(self):
        update = fake_update(user_id=789)
        context = SimpleNamespace(args=["09:30", "Alice,", "Bob"])

        with patch.object(bot_main, "create_hermes_job", AsyncMock()) as create_job, \
             patch.object(bot_main, "record_decision", AsyncMock()) as record:
            await bot_main.standup_schedule_cmd(update, context)

        create_job.assert_not_awaited()
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "rbac_denied:operator")
        self.assertEqual(record.await_args.kwargs["status"], "blocked_rbac")
        self.assertEqual(update.message.replies[0]["text"], "Restricted to Gray operators.")

    async def test_admin_can_approve_pending_request(self):
        update = fake_update(user_id=123)
        context = SimpleNamespace(args=["55"])
        approval = {"action_name": "schedule_web_monitor"}

        with patch.object(bot_main, "resolve_hermes_approval", AsyncMock(return_value=approval)), \
             patch.object(bot_main, "_decide_and_audit", AsyncMock(return_value=allowed_decision())) as audit:
            await bot_main.approve_cmd(update, context)

        audit.assert_awaited_once()
        self.assertIn("Approved Hermes request #55", update.message.replies[0]["text"])

    async def test_approve_requires_admin_role(self):
        update = fake_update(user_id=456)
        context = SimpleNamespace(args=["55"])

        with patch.object(bot_main, "resolve_hermes_approval", AsyncMock()) as resolve, \
             patch.object(bot_main, "record_decision", AsyncMock()) as record:
            await bot_main.approve_cmd(update, context)

        resolve.assert_not_awaited()
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "rbac_denied:admin")
        self.assertEqual(record.await_args.kwargs["status"], "blocked_rbac")
        self.assertEqual(update.message.replies[0]["text"], "Restricted to Gray admins.")

    async def test_ops_status_requires_admin_role(self):
        update = fake_update(user_id=456)
        context = SimpleNamespace()

        with patch.object(bot_main, "get_hermes_scheduler_health", AsyncMock()) as health, \
             patch.object(bot_main, "record_decision", AsyncMock()) as record:
            await bot_main.ops_status_cmd(update, context)

        health.assert_not_awaited()
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "rbac_denied:admin")
        self.assertEqual(record.await_args.kwargs["status"], "blocked_rbac")
        self.assertEqual(update.message.replies[0]["text"], "Restricted to Gray admins.")

    async def test_ops_status_reports_redacted_runtime_state(self):
        update = fake_update(user_id=123)
        context = SimpleNamespace()
        health = {
            "active_jobs": 2,
            "paused_jobs": 1,
            "due_jobs": 0,
            "errored_jobs": 1,
            "next_run_at": datetime(2026, 7, 10, 9, 30),
        }
        approvals = {"pending": 3, "expired": 4}

        with patch.object(bot_main, "_decide_and_audit", AsyncMock(return_value=allowed_decision())) as audit, \
             patch.object(bot_main, "get_hermes_scheduler_health", AsyncMock(return_value=health)), \
             patch.object(bot_main, "get_hermes_approval_counts", AsyncMock(return_value=approvals)), \
             patch.object(bot_main, "_hermes_scheduler", SimpleNamespace(is_running=True)), \
             patch.dict(os.environ, {
                 "MODEL_PROVIDER": "deepseek",
                 "DEEPSEEK_API_KEY": "sk-secret-value-that-must-not-leak",
                 "DEEPSEEK_MODEL": "deepseek-v4-flash",
                 "EMBEDDING_PROVIDER": "disabled",
                 "HERMES_GROUP_CHAT_MODE": "mention",
                 "GRAY_BOT_USERNAME": "GrayBot",
                 "HERMES_BACKUP_RETENTION_DAYS": "30",
             }, clear=False):
            await bot_main.ops_status_cmd(update, context)

        audit.assert_awaited_once()
        reply = update.message.replies[0]["text"]
        self.assertIn("*Gray ops status:*", reply)
        self.assertIn("DeepSeek key: `set`", reply)
        self.assertIn("Upload caps:", reply)
        self.assertIn("Scheduler: `running`", reply)
        self.assertIn("Pending approvals: `3`", reply)
        self.assertNotIn("sk-secret-value-that-must-not-leak", reply)

    async def test_forget_me_without_confirmation_shows_counts_only(self):
        update = fake_update(user_id=123)
        context = SimpleNamespace(args=[])
        counts = {
            "conversations": 2,
            "summaries": 1,
            "memory_facts": 3,
            "tasks": 4,
            "notes": 5,
            "company_memory_source_links": 6,
        }

        with patch.object(bot_main, "get_user_data_counts", AsyncMock(return_value=counts)) as get_counts, \
             patch.object(bot_main, "delete_user_data", AsyncMock()) as delete_data:
            await bot_main.forget_me_cmd(update, context)

        get_counts.assert_awaited_once_with(123)
        delete_data.assert_not_awaited()
        reply = update.message.replies[0]["text"]
        self.assertIn("Run `/forget_me CONFIRM`", reply)
        self.assertIn("Notes: 5", reply)

    async def test_forget_me_confirm_deletes_and_audits(self):
        update = fake_update(user_id=123)
        context = SimpleNamespace(args=["CONFIRM"])
        deleted = {
            "conversations": 2,
            "summaries": 1,
            "memory_facts": 3,
            "tasks": 4,
            "notes": 5,
            "company_memory_source_links": 6,
        }

        with patch.object(bot_main, "delete_user_data", AsyncMock(return_value=deleted)) as delete_data, \
             patch.object(bot_main, "record_decision", AsyncMock()) as record:
            await bot_main.forget_me_cmd(update, context)

        delete_data.assert_awaited_once_with(123)
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "delete_data")
        self.assertEqual(decision.action.params["scope"], "self_service_user_data")
        self.assertEqual(record.await_args.kwargs["status"], "self_service_deleted")
        self.assertIn("personal Gray data has been deleted", update.message.replies[0]["text"])


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bot_main._rate_limit_buckets.clear()
        self.role_patchers = [
            patch.object(bot_main, "ALLOWED_USERS", {123}),
            patch.object(bot_main, "RATE_LIMIT_MESSAGES", 2),
            patch.object(bot_main, "RATE_LIMIT_WINDOW_SECONDS", 60),
        ]
        for patcher in self.role_patchers:
            patcher.start()

    async def asyncTearDown(self):
        for patcher in reversed(self.role_patchers):
            patcher.stop()
        bot_main._rate_limit_buckets.clear()

    async def test_rate_limit_allows_requests_below_limit(self):
        update = fake_update(user_id=123)

        with patch.object(bot_main.time, "monotonic", side_effect=[100.0, 101.0]):
            self.assertTrue(await bot_main._within_rate_limit(update))
            self.assertTrue(await bot_main._within_rate_limit(update))

        self.assertEqual(update.message.replies, [])

    async def test_rate_limit_blocks_and_audits_excess_requests(self):
        update = fake_update(user_id=123)

        with patch.object(bot_main.time, "monotonic", side_effect=[100.0, 101.0, 102.0]), \
             patch.object(bot_main, "record_decision", AsyncMock()) as record:
            self.assertTrue(await bot_main._within_rate_limit(update))
            self.assertTrue(await bot_main._within_rate_limit(update))
            self.assertFalse(await bot_main._within_rate_limit(update))

        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "rate_limited")
        self.assertEqual(record.await_args.kwargs["status"], "blocked_rate_limit")
        self.assertIn("Rate limit reached", update.message.replies[0]["text"])

    async def test_rate_limited_wrapper_skips_handler_execution(self):
        update = fake_update(user_id=123)
        context = SimpleNamespace()
        handler = AsyncMock()
        wrapped = bot_main._rate_limited(handler)

        with patch.object(bot_main.time, "monotonic", side_effect=[100.0, 101.0, 102.0]), \
             patch.object(bot_main, "record_decision", AsyncMock()):
            await wrapped(update, context)
            await wrapped(update, context)
            await wrapped(update, context)

        self.assertEqual(handler.await_count, 2)

    async def test_rate_limiter_expires_old_entries(self):
        update = fake_update(user_id=123)

        with patch.object(bot_main.time, "monotonic", side_effect=[100.0, 101.0, 200.0]):
            self.assertTrue(await bot_main._within_rate_limit(update))
            self.assertTrue(await bot_main._within_rate_limit(update))
            self.assertTrue(await bot_main._within_rate_limit(update))

        self.assertEqual(update.message.replies, [])


class UploadLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.role_patchers = [
            patch.object(bot_main, "ALLOWED_USERS", {123}),
            patch.object(bot_main, "MAX_DOCUMENT_BYTES", 100),
            patch.object(bot_main, "MAX_VOICE_BYTES", 100),
            patch.object(bot_main, "MAX_PHOTO_BYTES", 100),
        ]
        for patcher in self.role_patchers:
            patcher.start()

    async def asyncTearDown(self):
        for patcher in reversed(self.role_patchers):
            patcher.stop()

    async def test_oversize_upload_is_rejected_and_audited(self):
        update = fake_update(user_id=123)

        with patch.object(bot_main, "record_decision", AsyncMock()) as record:
            rejected = await bot_main._reject_oversize_upload(update, "voice", 101, 100)

        self.assertTrue(rejected)
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "upload_too_large:voice")
        self.assertEqual(record.await_args.kwargs["status"], "blocked_upload_size")
        self.assertIn("too large", update.message.replies[0]["text"])

    async def test_unknown_upload_size_is_allowed_through(self):
        update = fake_update(user_id=123)

        with patch.object(bot_main, "record_decision", AsyncMock()) as record:
            rejected = await bot_main._reject_oversize_upload(update, "photo", None, 100)

        self.assertFalse(rejected)
        record.assert_not_awaited()
        self.assertEqual(update.message.replies, [])

    async def test_oversize_document_does_not_download(self):
        update = fake_update(user_id=123)
        update.message.caption = ""
        update.message.document = SimpleNamespace(
            file_name="large.pdf",
            file_size=101,
            get_file=AsyncMock(),
        )
        context = SimpleNamespace()

        with patch.object(bot_main, "should_process_message", return_value=True), \
             patch.object(bot_main, "record_decision", AsyncMock()):
            await bot_main.handle_document(update, context)

        update.message.document.get_file.assert_not_awaited()
        self.assertIn("document is too large", update.message.replies[0]["text"])


class TelegramErrorHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_handler_replies_and_audits_without_secret_text(self):
        update = fake_update(user_id=123)
        error = RuntimeError("sk-secret-value-that-must-not-enter-audit")
        context = SimpleNamespace(error=error)

        with patch.object(bot_main, "record_decision", AsyncMock()) as record, \
             patch.object(bot_main.logger, "error") as log_error:
            await bot_main.telegram_error_handler(update, context)

        log_error.assert_called_once()
        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "telegram_handler_error")
        self.assertEqual(decision.action.params["error_type"], "RuntimeError")
        self.assertNotIn("sk-secret-value-that-must-not-enter-audit", str(decision.action.params))
        self.assertEqual(record.await_args.kwargs["status"], "handler_error")
        self.assertIn("incident has been logged", update.message.replies[0]["text"])

    async def test_error_handler_handles_missing_update(self):
        context = SimpleNamespace(error=ValueError("no update"))

        with patch.object(bot_main, "record_decision", AsyncMock()) as record, \
             patch.object(bot_main.logger, "error"):
            await bot_main.telegram_error_handler(None, context)

        record.assert_awaited_once()
        decision = record.await_args.args[0]
        self.assertEqual(decision.action.name, "telegram_handler_error")
        self.assertIsNone(decision.action.actor_user_id)
        self.assertIsNone(decision.action.chat_id)
        self.assertEqual(decision.action.params["update_type"], "None")


class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_shutdown_closes_database_pool(self):
        bot_main._memory_workers = []
        bot_main._hermes_scheduler = None

        with patch.object(bot_main, "close_model_client", AsyncMock()) as close_model, \
             patch.object(bot_main, "close_embedding_client", AsyncMock()) as close_embedding, \
             patch.object(bot_main, "close_db_pool", AsyncMock()) as close_db:
            await bot_main.post_shutdown(SimpleNamespace())

        close_model.assert_awaited_once()
        close_embedding.assert_awaited_once()
        close_db.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
