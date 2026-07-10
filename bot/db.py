import asyncpg
import os
import json

DATABASE_URL = os.getenv("DATABASE_URL")
DB_MIN_POOL_SIZE = int(os.getenv("DB_MIN_POOL_SIZE", "1"))
DB_MAX_POOL_SIZE = int(os.getenv("DB_MAX_POOL_SIZE", "10"))
MAX_USER_MEMORY_ROWS = int(os.getenv("MAX_USER_MEMORY_ROWS", "30"))
HERMES_JOB_FAILURE_LIMIT = int(os.getenv("HERMES_JOB_FAILURE_LIMIT", "3"))
HERMES_AUDIT_RETENTION_DAYS = int(os.getenv("HERMES_AUDIT_RETENTION_DAYS", "180"))
HERMES_OPERATION_RETENTION_DAYS = int(os.getenv("HERMES_OPERATION_RETENTION_DAYS", "365"))
_pool = None


def _jsonb_to_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def _init_conn(conn):
    from pgvector.asyncpg import register_vector
    await register_vector(conn)


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=DB_MIN_POOL_SIZE,
            max_size=DB_MAX_POOL_SIZE,
            init=_init_conn,
        )
    return _pool


SUMMARY_TRIGGER_MESSAGES = int(os.getenv("SUMMARY_TRIGGER", "20"))


# ── Conversations ────────────────────────────────────────────────

async def get_conversation_history(user_id: int, limit: int = 10):
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT role, content FROM conversations
           WHERE telegram_user_id = $1
           ORDER BY created_at DESC LIMIT $2""",
        user_id, limit
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def save_message(user_id: int, role: str, content: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO conversations (telegram_user_id, role, content) VALUES ($1, $2, $3)",
        user_id, role, content
    )


async def clear_conversation(user_id: int):
    pool = await get_pool()
    await pool.execute("DELETE FROM conversations WHERE telegram_user_id = $1", user_id)
    await pool.execute("DELETE FROM conversation_summaries WHERE telegram_user_id = $1", user_id)


async def get_conversation_count(user_id: int) -> int:
    pool = await get_pool()
    return await pool.fetchval(
        "SELECT COUNT(*) FROM conversations WHERE telegram_user_id = $1", user_id
    )


async def save_conversation_summary(user_id: int, summary: str):
    """Store a compressed summary and wipe old raw messages."""
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO conversation_summaries (telegram_user_id, summary)
           VALUES ($1, $2)
           ON CONFLICT (telegram_user_id) DO UPDATE
           SET summary = EXCLUDED.summary, created_at = NOW()""",
        user_id, summary
    )
    # Keep only the 6 most recent raw messages after summarization
    await pool.execute(
        """DELETE FROM conversations
           WHERE telegram_user_id = $1
             AND id NOT IN (
               SELECT id FROM conversations
               WHERE telegram_user_id = $1
               ORDER BY created_at DESC LIMIT 6
             )""",
        user_id
    )


async def get_conversation_summary(user_id: int) -> str | None:
    pool = await get_pool()
    return await pool.fetchval(
        "SELECT summary FROM conversation_summaries WHERE telegram_user_id = $1",
        user_id
    )


# ── User memory ──────────────────────────────────────────────────

async def get_user_memory(user_id: int):
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT fact FROM (
               SELECT DISTINCT ON (lower(fact)) fact, created_at
               FROM user_memory
               WHERE telegram_user_id = $1
               ORDER BY lower(fact), created_at DESC
           ) AS deduped
           ORDER BY created_at DESC
           LIMIT $2""",
        user_id, MAX_USER_MEMORY_ROWS
    )
    return [r["fact"] for r in rows]


async def save_user_memory(user_id: int, fact: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO user_memory (telegram_user_id, fact) VALUES ($1, $2)",
        user_id, fact
    )


# ── Company memory ───────────────────────────────────────────────

async def save_company_memory(fact: str, category: str = "general",
                               source_user_id: int = None, embedding: list = None):
    pool = await get_pool()
    # Deduplicate: skip if a near-identical fact already exists (cosine similarity > 0.92)
    if embedding:
        dupe = await pool.fetchval(
            """SELECT 1 FROM company_memory
               WHERE embedding IS NOT NULL
                 AND 1 - (embedding <=> $1) > 0.92
               LIMIT 1""",
            embedding
        )
        if dupe:
            return  # close enough to an existing fact — don't save
    await pool.execute(
        """INSERT INTO company_memory (fact, category, source_user_id, embedding)
           VALUES ($1, $2, $3, $4)""",
        fact, category, source_user_id, embedding
    )


async def semantic_search_company_memory(query_embedding: list, limit: int = 5) -> list[str]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT fact, 1 - (embedding <=> $1) AS similarity
           FROM company_memory
           WHERE embedding IS NOT NULL
           ORDER BY embedding <=> $1
           LIMIT $2""",
        query_embedding, limit
    )
    return [r["fact"] for r in rows if r["similarity"] > 0.45]


async def text_search_company_memory(query: str, limit: int = 5) -> list[str]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT fact FROM company_memory
           WHERE to_tsvector('english', fact) @@ plainto_tsquery('english', $1)
           ORDER BY created_at DESC LIMIT $2""",
        query, limit
    )
    return [r["fact"] for r in rows]


# ── Tasks ────────────────────────────────────────────────────────

async def save_task(user_id: int, content: str, due_text: str = None) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO tasks (telegram_user_id, content, due_text)
           VALUES ($1, $2, $3) RETURNING id""",
        user_id, content, due_text
    )
    return row["id"]


async def get_open_tasks(user_id: int) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, content, due_text, created_at FROM tasks
           WHERE telegram_user_id = $1 AND status = 'open'
           ORDER BY created_at ASC""",
        user_id
    )
    return [dict(r) for r in rows]


async def complete_task(user_id: int, task_id: int) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE tasks SET status = 'done', completed_at = NOW()
           WHERE id = $1 AND telegram_user_id = $2 AND status = 'open'""",
        task_id, user_id
    )
    return result.split()[-1] == "1"


async def get_all_tasks(user_id: int, limit: int = 20) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, content, status, due_text, created_at, completed_at FROM tasks
           WHERE telegram_user_id = $1
           ORDER BY created_at DESC LIMIT $2""",
        user_id, limit
    )
    return [dict(r) for r in rows]


# ── Notes ────────────────────────────────────────────────────────

async def save_note(user_id: int, content: str, tags: list = None, embedding: list = None):
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO notes (telegram_user_id, content, tags, embedding)
           VALUES ($1, $2, $3, $4)""",
        user_id, content, tags or [], embedding
    )


async def get_recent_notes(user_id: int, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, content, tags, created_at FROM notes
           WHERE telegram_user_id = $1
           ORDER BY created_at DESC LIMIT $2""",
        user_id, limit
    )
    return [dict(r) for r in rows]


async def search_notes(user_id: int, query_embedding: list, limit: int = 5) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, content, tags, created_at,
                  1 - (embedding <=> $1) AS similarity
           FROM notes
           WHERE telegram_user_id = $2 AND embedding IS NOT NULL
           ORDER BY embedding <=> $1
           LIMIT $3""",
        query_embedding, user_id, limit
    )
    return [dict(r) for r in rows if r["similarity"] > 0.35]


# ── Hermes operations ────────────────────────────────────────────

async def save_hermes_audit_log(user_id: int | None, chat_id: int | None,
                                action_name: str, risk: str, decision: str,
                                status: str, details: dict | None = None):
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO hermes_audit_log
           (telegram_user_id, chat_id, action_name, risk, decision, status, details)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)""",
        user_id, chat_id, action_name, risk, decision, status,
        json.dumps(details or {}),
    )


async def get_recent_hermes_audit(chat_id: int, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, telegram_user_id, action_name, risk, decision, status, details, created_at
           FROM hermes_audit_log
           WHERE chat_id = $1
           ORDER BY created_at DESC
           LIMIT $2""",
        chat_id, limit,
    )
    return [dict(r) for r in rows]


async def create_hermes_approval_request(user_id: int | None, chat_id: int,
                                         action_name: str, risk: str,
                                         prompt: str, reason: str,
                                         params: dict | None = None,
                                         expires_at=None) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO hermes_approval_requests
           (telegram_user_id, chat_id, action_name, risk, prompt, reason, params, expires_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, COALESCE($8::timestamp, NOW() + INTERVAL '24 hours'))
           RETURNING id""",
        user_id, chat_id, action_name, risk, prompt, reason,
        json.dumps(params or {}), expires_at,
    )
    return row["id"]


async def get_pending_hermes_approvals(chat_id: int, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, telegram_user_id, action_name, risk, prompt, reason,
                  params, requested_at, expires_at
           FROM hermes_approval_requests
           WHERE chat_id = $1 AND status = 'pending'
           ORDER BY requested_at ASC
           LIMIT $2""",
        chat_id, limit,
    )
    return [dict(r) for r in rows]


async def resolve_hermes_approval(approval_id: int, chat_id: int,
                                  resolved_by: int, status: str,
                                  note: str | None = None) -> dict | None:
    if status not in {"approved", "denied"}:
        raise ValueError("approval status must be approved or denied")
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE hermes_approval_requests
           SET status = $1, resolved_by = $2, resolved_at = NOW(), resolution_note = $3
           WHERE id = $4 AND chat_id = $5 AND status = 'pending' AND expires_at > NOW()
           RETURNING id, telegram_user_id, chat_id, action_name, risk, status,
                     prompt, reason, params, requested_at, resolved_by,
                     resolved_at, resolution_note, expires_at""",
        status, resolved_by, note, approval_id, chat_id,
    )
    return dict(row) if row else None


async def get_hermes_approval(approval_id: int, chat_id: int) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT id, telegram_user_id, chat_id, action_name, risk, status,
                  prompt, reason, params, requested_at, resolved_by,
                  resolved_at, resolution_note, expires_at
           FROM hermes_approval_requests
           WHERE id = $1 AND chat_id = $2""",
        approval_id, chat_id,
    )
    return dict(row) if row else None


async def expire_hermes_approvals() -> int:
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE hermes_approval_requests
           SET status = 'expired',
               resolved_at = NOW(),
               resolution_note = 'Expired without approval.'
           WHERE status = 'pending' AND expires_at <= NOW()"""
    )
    return int(result.split()[-1])


async def get_hermes_approval_counts(chat_id: int | None = None) -> dict:
    pool = await get_pool()
    if chat_id is None:
        row = await pool.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                 COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                 COUNT(*) FILTER (WHERE status = 'denied') AS denied,
                 COUNT(*) FILTER (WHERE status = 'expired') AS expired
               FROM hermes_approval_requests"""
        )
    else:
        row = await pool.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                 COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                 COUNT(*) FILTER (WHERE status = 'denied') AS denied,
                 COUNT(*) FILTER (WHERE status = 'expired') AS expired
               FROM hermes_approval_requests
               WHERE chat_id = $1""",
            chat_id,
        )
    return dict(row) if row else {"pending": 0, "approved": 0, "denied": 0, "expired": 0}


async def create_hermes_job(chat_id: int, created_by: int | None,
                            job_type: str, schedule_kind: str,
                            schedule_value: str, next_run_at,
                            payload: dict | None = None) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO hermes_jobs
           (chat_id, created_by, job_type, schedule_kind, schedule_value, next_run_at, payload)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
           RETURNING id""",
        chat_id, created_by, job_type, schedule_kind, schedule_value,
        next_run_at, json.dumps(payload or {}),
    )
    return row["id"]


async def get_hermes_jobs(chat_id: int, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, chat_id, created_by, job_type, status, schedule_kind,
                  schedule_value, next_run_at, last_run_at, last_error,
                  consecutive_failures, payload, created_at
           FROM hermes_jobs
           WHERE chat_id = $1
           ORDER BY status ASC, next_run_at ASC
           LIMIT $2""",
        chat_id, limit,
    )
    return [dict(r) for r in rows]


async def pause_hermes_job(chat_id: int, job_id: int) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE hermes_jobs
           SET status = 'paused', updated_at = NOW()
           WHERE id = $1 AND chat_id = $2 AND status = 'active'""",
        job_id, chat_id,
    )
    return result.split()[-1] == "1"


async def resume_hermes_job(chat_id: int, job_id: int, next_run_at) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE hermes_jobs
           SET status = 'active', next_run_at = $1, locked_at = NULL, updated_at = NOW()
           WHERE id = $2 AND chat_id = $3 AND status = 'paused'""",
        next_run_at, job_id, chat_id,
    )
    return result.split()[-1] == "1"


async def remove_hermes_job(chat_id: int, job_id: int) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE hermes_jobs
           SET status = 'removed', locked_at = NULL, updated_at = NOW()
           WHERE id = $1 AND chat_id = $2 AND status IN ('active', 'paused')""",
        job_id, chat_id,
    )
    return result.split()[-1] == "1"


async def get_due_hermes_jobs(limit: int = 5) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, chat_id, created_by, job_type, schedule_kind,
                  schedule_value, next_run_at, payload
           FROM hermes_jobs
           WHERE status = 'active'
             AND next_run_at <= NOW()
             AND (locked_at IS NULL OR locked_at < NOW() - INTERVAL '10 minutes')
           ORDER BY next_run_at ASC
           LIMIT $1""",
        limit,
    )
    return [dict(r) for r in rows]


async def claim_hermes_job(job_id: int) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE hermes_jobs
           SET locked_at = NOW(), updated_at = NOW()
           WHERE id = $1
             AND status = 'active'
             AND (locked_at IS NULL OR locked_at < NOW() - INTERVAL '10 minutes')
           RETURNING id, chat_id, created_by, job_type, schedule_kind,
                     schedule_value, next_run_at, payload""",
        job_id,
    )
    return dict(row) if row else None


async def mark_hermes_job_run(job_id: int, next_run_at) -> None:
    pool = await get_pool()
    await pool.execute(
        """UPDATE hermes_jobs
           SET last_run_at = NOW(), next_run_at = $1, locked_at = NULL,
               last_error = NULL, consecutive_failures = 0, updated_at = NOW()
           WHERE id = $2""",
        next_run_at, job_id,
    )


async def mark_hermes_job_failed(job_id: int, error: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE hermes_jobs
           SET last_error = $1,
               consecutive_failures = consecutive_failures + 1,
               status = CASE
                   WHEN consecutive_failures + 1 >= $3 THEN 'paused'
                   ELSE status
               END,
               locked_at = NULL,
               updated_at = NOW()
           WHERE id = $2
           RETURNING id, chat_id, created_by, job_type, status,
                     consecutive_failures, last_error""",
        error[:1000], job_id, HERMES_JOB_FAILURE_LIMIT,
    )
    return dict(row) if row else None


async def get_hermes_scheduler_health() -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE status = 'active') AS active_jobs,
             COUNT(*) FILTER (WHERE status = 'paused') AS paused_jobs,
             COUNT(*) FILTER (WHERE status = 'active' AND next_run_at <= NOW()) AS due_jobs,
             COUNT(*) FILTER (WHERE status = 'active' AND last_error IS NOT NULL) AS errored_jobs,
             MIN(next_run_at) FILTER (WHERE status = 'active') AS next_run_at
           FROM hermes_jobs"""
    )
    return dict(row) if row else {
        "active_jobs": 0,
        "paused_jobs": 0,
        "due_jobs": 0,
        "errored_jobs": 0,
        "next_run_at": None,
    }


async def get_hermes_retention_counts(audit_days: int | None = None,
                                      operation_days: int | None = None) -> dict:
    audit_days = audit_days or HERMES_AUDIT_RETENTION_DAYS
    operation_days = operation_days or HERMES_OPERATION_RETENTION_DAYS
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT
             (SELECT COUNT(*) FROM hermes_audit_log
              WHERE created_at < NOW() - ($1::int * INTERVAL '1 day')) AS audit_log,
             (SELECT COUNT(*) FROM hermes_approval_requests
              WHERE status IN ('approved', 'denied', 'expired')
                AND requested_at < NOW() - ($2::int * INTERVAL '1 day')) AS approval_requests,
             (SELECT COUNT(*) FROM hermes_jobs
              WHERE status IN ('removed', 'paused')
                AND updated_at < NOW() - ($2::int * INTERVAL '1 day')) AS jobs,
             (SELECT COUNT(*) FROM standup_sessions
              WHERE status = 'closed'
                AND completed_at < NOW() - ($2::int * INTERVAL '1 day')) AS standup_sessions""",
        audit_days, operation_days,
    )
    return dict(row) if row else {
        "audit_log": 0,
        "approval_requests": 0,
        "jobs": 0,
        "standup_sessions": 0,
    }


async def prune_hermes_retention(audit_days: int | None = None,
                                 operation_days: int | None = None) -> dict:
    audit_days = audit_days or HERMES_AUDIT_RETENTION_DAYS
    operation_days = operation_days or HERMES_OPERATION_RETENTION_DAYS
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            audit = await conn.execute(
                """DELETE FROM hermes_audit_log
                   WHERE created_at < NOW() - ($1::int * INTERVAL '1 day')""",
                audit_days,
            )
            approvals = await conn.execute(
                """DELETE FROM hermes_approval_requests
                   WHERE status IN ('approved', 'denied', 'expired')
                     AND requested_at < NOW() - ($1::int * INTERVAL '1 day')""",
                operation_days,
            )
            jobs = await conn.execute(
                """DELETE FROM hermes_jobs
                   WHERE status IN ('removed', 'paused')
                     AND updated_at < NOW() - ($1::int * INTERVAL '1 day')""",
                operation_days,
            )
            standups = await conn.execute(
                """DELETE FROM standup_sessions
                   WHERE status = 'closed'
                     AND completed_at < NOW() - ($1::int * INTERVAL '1 day')""",
                operation_days,
            )
    return {
        "audit_log": _row_count(audit),
        "approval_requests": _row_count(approvals),
        "jobs": _row_count(jobs),
        "standup_sessions": _row_count(standups),
    }


def _row_count(result: str) -> int:
    try:
        return int(result.split()[-1])
    except (AttributeError, ValueError, IndexError):
        return 0


async def create_standup_session(chat_id: int, created_by: int, participants: list[str]) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO standup_sessions (chat_id, created_by, participants)
           VALUES ($1, $2, $3) RETURNING id""",
        chat_id, created_by, participants,
    )
    return row["id"]


async def get_open_standup_session(chat_id: int) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT id, chat_id, created_by, status, participants, updates, summary, created_at
           FROM standup_sessions
           WHERE chat_id = $1 AND status = 'open'
           ORDER BY created_at DESC
           LIMIT 1""",
        chat_id,
    )
    return dict(row) if row else None


async def save_standup_update(chat_id: int, participant: str, text: str) -> dict | None:
    session = await get_open_standup_session(chat_id)
    if not session:
        return None
    updates = _jsonb_to_dict(session.get("updates"))
    updates[participant] = text
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE standup_sessions
           SET updates = $1::jsonb
           WHERE id = $2
           RETURNING id, chat_id, created_by, status, participants, updates, summary, created_at""",
        json.dumps(updates), session["id"],
    )
    return dict(row)


async def close_standup_session(chat_id: int, summary: str) -> dict | None:
    session = await get_open_standup_session(chat_id)
    if not session:
        return None
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE standup_sessions
           SET status = 'closed', summary = $1, completed_at = NOW()
           WHERE id = $2
           RETURNING id, chat_id, created_by, status, participants, updates, summary, created_at, completed_at""",
        summary, session["id"],
    )
    return dict(row)
