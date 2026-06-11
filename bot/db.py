import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")
DB_MIN_POOL_SIZE = int(os.getenv("DB_MIN_POOL_SIZE", "1"))
DB_MAX_POOL_SIZE = int(os.getenv("DB_MAX_POOL_SIZE", "10"))
MAX_USER_MEMORY_ROWS = int(os.getenv("MAX_USER_MEMORY_ROWS", "30"))
_pool = None


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
