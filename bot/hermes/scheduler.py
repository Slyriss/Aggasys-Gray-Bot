from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .workflows import (
    missing_standup_participants,
    parse_participants,
    standup_chase_message,
    summarize_standup_updates,
)
from .monitoring import web_monitor_message

logger = logging.getLogger(__name__)

HERMES_SCHEDULER_INTERVAL_SECONDS = int(os.getenv("HERMES_SCHEDULER_INTERVAL_SECONDS", "30"))
HERMES_SCHEDULER_BATCH_SIZE = int(os.getenv("HERMES_SCHEDULER_BATCH_SIZE", "5"))
HERMES_TIMEZONE = os.getenv("HERMES_TIMEZONE", "Asia/Singapore")


def parse_daily_time(value: str) -> time:
    text = value.strip()
    for fmt in ("%H:%M", "%H%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError("time must be HH:MM, for example 09:30")


def next_daily_run(now: datetime, daily_at: time, tz_name: str = HERMES_TIMEZONE) -> datetime:
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    candidate = datetime.combine(local_now.date(), daily_at, tzinfo=tz)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.replace(tzinfo=None)


def standup_prompt(participants: list[str], session_id: int | None = None) -> str:
    names = ", ".join(participants) if participants else "team"
    header = f"Daily standup #{session_id} time for {names}." if session_id else f"Daily standup time for {names}."
    return (
        f"{header}\n"
        "Please post: yesterday, today, blockers.\n"
        "Use /standup_update <your update>."
    )


def configured_admin_user_ids(raw: str | None = None) -> list[int]:
    source = os.getenv("ADMIN_USERS", "") if raw is None else raw
    return [int(uid.strip()) for uid in source.split(",") if uid.strip().isdigit()]


def summary_recipient_tier(value: Any) -> str:
    tier = str(value or "chat").strip().lower()
    return tier if tier in {"chat", "admins", "both"} else "chat"


class HermesScheduler:
    def __init__(self, app, interval_seconds: int = HERMES_SCHEDULER_INTERVAL_SECONDS):
        self.app = app
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return bool(self._task and not self._task.done() and not self._stopping.is_set())

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run_loop(), name="hermes-scheduler")
        logger.info("Hermes scheduler started interval=%ss", self.interval_seconds)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.info("Hermes scheduler stopped")

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.run_once()
            except Exception as exc:
                logger.warning("Hermes scheduler tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def run_once(self) -> int:
        from db import (
            claim_hermes_job,
            expire_hermes_approvals,
            get_due_hermes_jobs,
            mark_hermes_job_failed,
            mark_hermes_job_run,
        )

        expired = await expire_hermes_approvals()
        if expired:
            logger.info("Expired %s Hermes approval request(s)", expired)

        due = await get_due_hermes_jobs(limit=HERMES_SCHEDULER_BATCH_SIZE)
        ran = 0
        for job in due:
            claimed = await claim_hermes_job(job["id"])
            if not claimed:
                continue
            try:
                await self._run_job(claimed)
                next_run = self._next_run_for_job(claimed)
                await mark_hermes_job_run(claimed["id"], next_run)
                ran += 1
            except Exception as exc:
                logger.exception("Hermes job %s failed", claimed["id"])
                failed_job = await mark_hermes_job_failed(claimed["id"], str(exc))
                if failed_job and failed_job.get("status") == "paused":
                    await self._audit_job_auto_paused(failed_job)
        return ran

    async def _audit_job_auto_paused(self, job: dict[str, Any]) -> None:
        from db import save_hermes_audit_log

        await save_hermes_audit_log(
            user_id=job.get("created_by"),
            chat_id=job.get("chat_id"),
            action_name="scheduled_job_auto_paused",
            risk="low",
            decision="allowed",
            status="paused",
            details={
                "job_id": job.get("id"),
                "job_type": job.get("job_type"),
                "consecutive_failures": job.get("consecutive_failures"),
                "last_error": job.get("last_error"),
            },
        )

    async def _run_job(self, job: dict[str, Any]) -> None:
        if job["job_type"] == "daily_standup":
            from db import (
                create_standup_session,
                get_open_standup_session,
                save_hermes_audit_log,
            )

            payload = _jsonb_dict(job.get("payload"))
            participants = payload.get("participants") or []
            if isinstance(participants, str):
                participants = parse_participants(participants)
            session = await get_open_standup_session(job["chat_id"])
            session_id = session["id"] if session else await create_standup_session(
                job["chat_id"],
                job.get("created_by") or 0,
                participants,
            )
            await self.app.bot.send_message(
                chat_id=job["chat_id"],
                text=standup_prompt(participants, session_id=session_id),
            )
            await save_hermes_audit_log(
                user_id=job.get("created_by"),
                chat_id=job["chat_id"],
                action_name="scheduled_daily_standup",
                risk="low",
                decision="allowed",
                status="executed",
                details={"job_id": job["id"], "standup_session_id": session_id},
            )
            return
        if job["job_type"] == "standup_chase":
            from db import get_open_standup_session, save_hermes_audit_log

            session = await get_open_standup_session(job["chat_id"])
            if not session:
                await save_hermes_audit_log(
                    user_id=job.get("created_by"),
                    chat_id=job["chat_id"],
                    action_name="scheduled_standup_chase",
                    risk="low",
                    decision="allowed",
                    status="skipped",
                    details={"job_id": job["id"], "reason": "no_open_standup"},
                )
                return
            updates = _jsonb_dict(session.get("updates"))
            participants = list(session.get("participants") or [])
            missing = missing_standup_participants(participants, updates)
            if not missing:
                await save_hermes_audit_log(
                    user_id=job.get("created_by"),
                    chat_id=job["chat_id"],
                    action_name="scheduled_standup_chase",
                    risk="low",
                    decision="allowed",
                    status="skipped",
                    details={
                        "job_id": job["id"],
                        "standup_session_id": session["id"],
                        "reason": "all_updates_in",
                    },
                )
                return
            await self.app.bot.send_message(
                chat_id=job["chat_id"],
                text=standup_chase_message(missing),
            )
            await save_hermes_audit_log(
                user_id=job.get("created_by"),
                chat_id=job["chat_id"],
                action_name="scheduled_standup_chase",
                risk="low",
                decision="allowed",
                status="executed",
                details={
                    "job_id": job["id"],
                    "standup_session_id": session["id"],
                    "missing": missing,
                },
            )
            return
        if job["job_type"] == "standup_summary":
            from db import close_standup_session, get_open_standup_session, save_hermes_audit_log

            payload = _jsonb_dict(job.get("payload"))
            recipient_tier = summary_recipient_tier(payload.get("summary_recipients"))
            session = await get_open_standup_session(job["chat_id"])
            if not session:
                await save_hermes_audit_log(
                    user_id=job.get("created_by"),
                    chat_id=job["chat_id"],
                    action_name="scheduled_standup_summary",
                    risk="low",
                    decision="allowed",
                    status="skipped",
                    details={
                        "job_id": job["id"],
                        "recipient_tier": recipient_tier,
                        "reason": "no_open_standup",
                    },
                )
                return
            updates = _jsonb_dict(session.get("updates"))
            participants = list(session.get("participants") or [])
            missing = missing_standup_participants(participants, updates)
            summary = summarize_standup_updates(updates, missing)
            closed = await close_standup_session(job["chat_id"], summary)
            session_id = closed["id"] if closed else session["id"]
            delivered_to: list[str] = []
            if recipient_tier in {"chat", "both"}:
                await self.app.bot.send_message(chat_id=job["chat_id"], text=summary)
                delivered_to.append("chat")
            if recipient_tier in {"admins", "both"}:
                for admin_id in configured_admin_user_ids():
                    await self.app.bot.send_message(
                        chat_id=admin_id,
                        text=f"Standup summary from chat {job['chat_id']}:\n\n{summary}",
                    )
                delivered_to.append("admins")
            await save_hermes_audit_log(
                user_id=job.get("created_by"),
                chat_id=job["chat_id"],
                action_name="scheduled_standup_summary",
                risk="low",
                decision="allowed",
                status="executed",
                details={
                    "job_id": job["id"],
                    "standup_session_id": session_id,
                    "recipient_tier": recipient_tier,
                    "delivered_to": delivered_to,
                },
            )
            return
        if job["job_type"] == "web_monitor":
            from db import save_hermes_audit_log
            from tools import web_search

            payload = _jsonb_dict(job.get("payload"))
            query = str(payload.get("query") or "").strip()
            if not query:
                await save_hermes_audit_log(
                    user_id=job.get("created_by"),
                    chat_id=job["chat_id"],
                    action_name="scheduled_web_monitor",
                    risk="read_only",
                    decision="allowed",
                    status="skipped",
                    details={"job_id": job["id"], "reason": "missing_query"},
                )
                return
            result = await web_search(query)
            await self.app.bot.send_message(
                chat_id=job["chat_id"],
                text=web_monitor_message(query, result),
            )
            await save_hermes_audit_log(
                user_id=job.get("created_by"),
                chat_id=job["chat_id"],
                action_name="scheduled_web_monitor",
                risk="read_only",
                decision="allowed",
                status="executed",
                details={"job_id": job["id"], "query": query},
            )
            return
        logger.warning("Unknown Hermes job type: %s", job["job_type"])
        raise ValueError(f"Unknown Hermes job type: {job['job_type']}")

    def _next_run_for_job(self, job: dict[str, Any]) -> datetime:
        if job["schedule_kind"] == "daily":
            daily_at = parse_daily_time(job["schedule_value"])
            return next_daily_run(datetime.now(ZoneInfo(HERMES_TIMEZONE)), daily_at)
        return datetime.now() + timedelta(hours=24)


def _jsonb_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
