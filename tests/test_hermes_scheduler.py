import os
import sys
import types
import unittest
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from hermes.scheduler import HermesScheduler


class FakeBot:
    def __init__(self, fail_send=False):
        self.messages = []
        self.fail_send = fail_send

    async def send_message(self, chat_id, text):
        if self.fail_send:
            raise RuntimeError("telegram send failed")
        self.messages.append({"chat_id": chat_id, "text": text})


class FakeApp:
    def __init__(self, fail_send=False):
        self.bot = FakeBot(fail_send=fail_send)


class FakeDb(types.ModuleType):
    def __init__(self):
        super().__init__("db")
        self.job = {
            "id": 11,
            "chat_id": -100,
            "created_by": 123,
            "job_type": "daily_standup",
            "schedule_kind": "daily",
            "schedule_value": "09:30",
            "next_run_at": datetime(2026, 7, 9, 9, 30),
            "payload": {"participants": ["Alice", "Bob"]},
        }
        self.marked_runs = []
        self.failures = []
        self.audits = []
        self.sessions = []
        self.expired_calls = 0
        self.open_session = None

    async def expire_hermes_approvals(self):
        self.expired_calls += 1
        return 0

    async def get_due_hermes_jobs(self, limit=5):
        return [dict(self.job)]

    async def claim_hermes_job(self, job_id):
        if job_id == self.job["id"]:
            return dict(self.job)
        return None

    async def mark_hermes_job_run(self, job_id, next_run_at):
        self.marked_runs.append({"job_id": job_id, "next_run_at": next_run_at})

    async def mark_hermes_job_failed(self, job_id, error):
        self.failures.append({"job_id": job_id, "error": error})
        return None

    async def get_open_standup_session(self, chat_id):
        return self.open_session

    async def create_standup_session(self, chat_id, created_by, participants):
        session_id = 77
        self.sessions.append({
            "id": session_id,
            "chat_id": chat_id,
            "created_by": created_by,
            "participants": participants,
        })
        return session_id

    async def save_hermes_audit_log(self, **kwargs):
        self.audits.append(kwargs)


class FakeTools(types.ModuleType):
    def __init__(self):
        super().__init__("tools")
        self.queries = []

    async def web_search(self, query):
        self.queries.append(query)
        return "Tender result\nSource: https://example.com/tender"


class HermesSchedulerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_executes_due_standup_job(self):
        fake_db = FakeDb()
        previous_db = sys.modules.get("db")
        sys.modules["db"] = fake_db
        try:
            app = FakeApp()
            scheduler = HermesScheduler(app=app)

            ran = await scheduler.run_once()

            self.assertEqual(ran, 1)
            self.assertEqual(fake_db.expired_calls, 1)
            self.assertEqual(fake_db.failures, [])
            self.assertEqual(len(fake_db.marked_runs), 1)
            self.assertEqual(fake_db.sessions[0]["participants"], ["Alice", "Bob"])
            self.assertEqual(app.bot.messages[0]["chat_id"], -100)
            self.assertIn("Daily standup #77", app.bot.messages[0]["text"])
            self.assertEqual(fake_db.audits[0]["action_name"], "scheduled_daily_standup")
            self.assertEqual(fake_db.audits[0]["details"]["standup_session_id"], 77)
        finally:
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db

    async def test_run_once_executes_standup_chase_for_missing_people(self):
        fake_db = FakeDb()
        fake_db.job = {
            **fake_db.job,
            "job_type": "standup_chase",
            "payload": {},
        }
        fake_db.open_session = {
            "id": 88,
            "chat_id": -100,
            "created_by": 123,
            "participants": ["Alice", "Bob"],
            "updates": {"Alice": "done yesterday, testing today, no blockers"},
        }
        previous_db = sys.modules.get("db")
        sys.modules["db"] = fake_db
        try:
            app = FakeApp()
            scheduler = HermesScheduler(app=app)

            ran = await scheduler.run_once()

            self.assertEqual(ran, 1)
            self.assertEqual(len(fake_db.marked_runs), 1)
            self.assertEqual(app.bot.messages[0]["chat_id"], -100)
            self.assertIn("@Bob", app.bot.messages[0]["text"])
            self.assertNotIn("@Alice", app.bot.messages[0]["text"])
            self.assertEqual(fake_db.audits[0]["action_name"], "scheduled_standup_chase")
            self.assertEqual(fake_db.audits[0]["status"], "executed")
            self.assertEqual(fake_db.audits[0]["details"]["missing"], ["Bob"])
        finally:
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db

    async def test_run_once_skips_standup_chase_when_everyone_updated(self):
        fake_db = FakeDb()
        fake_db.job = {
            **fake_db.job,
            "job_type": "standup_chase",
            "payload": {},
        }
        fake_db.open_session = {
            "id": 88,
            "chat_id": -100,
            "created_by": 123,
            "participants": ["Alice", "Bob"],
            "updates": {"Alice": "done", "Bob": "done"},
        }
        previous_db = sys.modules.get("db")
        sys.modules["db"] = fake_db
        try:
            app = FakeApp()
            scheduler = HermesScheduler(app=app)

            ran = await scheduler.run_once()

            self.assertEqual(ran, 1)
            self.assertEqual(app.bot.messages, [])
            self.assertEqual(fake_db.audits[0]["status"], "skipped")
            self.assertEqual(fake_db.audits[0]["details"]["reason"], "all_updates_in")
        finally:
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db

    async def test_run_once_executes_web_monitor_job(self):
        fake_db = FakeDb()
        fake_tools = FakeTools()
        fake_db.job = {
            **fake_db.job,
            "job_type": "web_monitor",
            "payload": {"query": "Singapore SME AI tenders"},
        }
        previous_db = sys.modules.get("db")
        previous_tools = sys.modules.get("tools")
        sys.modules["db"] = fake_db
        sys.modules["tools"] = fake_tools
        try:
            app = FakeApp()
            scheduler = HermesScheduler(app=app)

            ran = await scheduler.run_once()

            self.assertEqual(ran, 1)
            self.assertEqual(fake_tools.queries, ["Singapore SME AI tenders"])
            self.assertEqual(len(fake_db.marked_runs), 1)
            self.assertIn("Web monitor update: Singapore SME AI tenders", app.bot.messages[0]["text"])
            self.assertIn("Tender result", app.bot.messages[0]["text"])
            self.assertEqual(fake_db.audits[0]["action_name"], "scheduled_web_monitor")
            self.assertEqual(fake_db.audits[0]["status"], "executed")
        finally:
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db
            if previous_tools is None:
                sys.modules.pop("tools", None)
            else:
                sys.modules["tools"] = previous_tools

    async def test_run_once_skips_web_monitor_without_query(self):
        fake_db = FakeDb()
        fake_tools = FakeTools()
        fake_db.job = {
            **fake_db.job,
            "job_type": "web_monitor",
            "payload": {},
        }
        previous_db = sys.modules.get("db")
        previous_tools = sys.modules.get("tools")
        sys.modules["db"] = fake_db
        sys.modules["tools"] = fake_tools
        try:
            app = FakeApp()
            scheduler = HermesScheduler(app=app)

            ran = await scheduler.run_once()

            self.assertEqual(ran, 1)
            self.assertEqual(fake_tools.queries, [])
            self.assertEqual(app.bot.messages, [])
            self.assertEqual(fake_db.audits[0]["status"], "skipped")
            self.assertEqual(fake_db.audits[0]["details"]["reason"], "missing_query")
        finally:
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db
            if previous_tools is None:
                sys.modules.pop("tools", None)
            else:
                sys.modules["tools"] = previous_tools

    async def test_run_once_marks_failed_job_without_advancing(self):
        fake_db = FakeDb()
        previous_db = sys.modules.get("db")
        sys.modules["db"] = fake_db
        try:
            app = FakeApp(fail_send=True)
            scheduler = HermesScheduler(app=app)

            with self.assertLogs("hermes.scheduler", level="ERROR") as logs:
                ran = await scheduler.run_once()

            self.assertEqual(ran, 0)
            self.assertTrue(any("Hermes job 11 failed" in line for line in logs.output))
            self.assertEqual(fake_db.expired_calls, 1)
            self.assertEqual(fake_db.marked_runs, [])
            self.assertEqual(len(fake_db.failures), 1)
            self.assertEqual(fake_db.failures[0]["job_id"], 11)
            self.assertIn("telegram send failed", fake_db.failures[0]["error"])
        finally:
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db

    async def test_run_once_audits_auto_paused_failed_job(self):
        fake_db = FakeDb()

        async def mark_failed(job_id, error):
            fake_db.failures.append({"job_id": job_id, "error": error})
            return {
                "id": job_id,
                "chat_id": -100,
                "created_by": 123,
                "job_type": "daily_standup",
                "status": "paused",
                "consecutive_failures": 3,
                "last_error": error,
            }

        fake_db.mark_hermes_job_failed = mark_failed
        previous_db = sys.modules.get("db")
        sys.modules["db"] = fake_db
        try:
            app = FakeApp(fail_send=True)
            scheduler = HermesScheduler(app=app)

            with self.assertLogs("hermes.scheduler", level="ERROR"):
                ran = await scheduler.run_once()

            self.assertEqual(ran, 0)
            self.assertEqual(fake_db.audits[0]["action_name"], "scheduled_job_auto_paused")
            self.assertEqual(fake_db.audits[0]["status"], "paused")
            self.assertEqual(fake_db.audits[0]["details"]["consecutive_failures"], 3)
            self.assertIn("telegram send failed", fake_db.audits[0]["details"]["last_error"])
        finally:
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db


if __name__ == "__main__":
    unittest.main()
