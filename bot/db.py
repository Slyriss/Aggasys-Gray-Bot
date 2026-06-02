import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool

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
        """INSERT INTO conversations (telegram_user_id, role, content)
           VALUES ($1, $2, $3)""",
        user_id, role, content
    )

async def get_user_memory(user_id: int):
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT fact FROM user_memory WHERE telegram_user_id = $1",
        user_id
    )
    return [r["fact"] for r in rows]

async def save_user_memory(user_id: int, fact: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO user_memory (telegram_user_id, fact) VALUES ($1, $2)",
        user_id, fact
    )

async def clear_conversation(user_id: int):
    pool = await get_pool()
    await pool.execute(
        "DELETE FROM conversations WHERE telegram_user_id = $1",
        user_id
    )
