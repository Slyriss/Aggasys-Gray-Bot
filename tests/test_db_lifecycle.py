import os
import sys
import types
import unittest
import importlib.util
from unittest.mock import AsyncMock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

asyncpg = types.ModuleType("asyncpg")
asyncpg.create_pool = AsyncMock()
sys.modules.setdefault("asyncpg", asyncpg)

pgvector = types.ModuleType("pgvector")
pgvector_asyncpg = types.ModuleType("pgvector.asyncpg")
pgvector_asyncpg.register_vector = AsyncMock()
sys.modules.setdefault("pgvector", pgvector)
sys.modules.setdefault("pgvector.asyncpg", pgvector_asyncpg)

spec = importlib.util.spec_from_file_location("db_lifecycle_target", os.path.join(BOT_DIR, "db.py"))
db = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(db)


class DbLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        db._pool = None

    async def test_close_pool_closes_existing_pool_and_resets_global(self):
        pool = AsyncMock()
        db._pool = pool

        await db.close_pool()

        pool.close.assert_awaited_once()
        self.assertIsNone(db._pool)

    async def test_close_pool_is_noop_without_pool(self):
        db._pool = None

        await db.close_pool()

        self.assertIsNone(db._pool)


if __name__ == "__main__":
    unittest.main()
