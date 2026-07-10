"""Ingest the public Aggasys company-basics seed into Gray's wiki.

Requires a configured .env with DATABASE_URL and DeepSeek model settings.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
SEED_PATH = ROOT / "docs" / "AGGASYS_PUBLIC_KNOWLEDGE_SEED.md"
SEED_MARKER_PATH = "decisions/public-knowledge-seed"
SEED_LOCK_ID = 63012135
LEGACY_SEED_PATHS = [
    SEED_MARKER_PATH,
    "staff/company-overview",
    "staff/aggasys-overview",
    "staff/gray-onboarding",
]


def _load_bot_modules() -> None:
    sys.path.insert(0, str(BOT_DIR))


def _seed_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _try_seed_lock() -> bool:
    from db import get_pool

    pool = await get_pool()
    return bool(await pool.fetchval("SELECT pg_try_advisory_lock($1)", SEED_LOCK_ID))


async def _release_seed_lock() -> None:
    from db import get_pool

    pool = await get_pool()
    await pool.fetchval("SELECT pg_advisory_unlock($1)", SEED_LOCK_ID)


async def _seed_already_loaded(seed_name: str, seed_sha256: str) -> str | None:
    from db import get_pool

    pool = await get_pool()
    marker_content = await pool.fetchval(
        "SELECT content FROM wiki_pages WHERE path = $1",
        SEED_MARKER_PATH,
    )
    if marker_content:
        if f"Seed SHA256: {seed_sha256}" in marker_content:
            return SEED_MARKER_PATH
        if "Seed SHA256:" not in marker_content:
            return SEED_MARKER_PATH
        return None

    legacy_path = await pool.fetchval(
        """SELECT path
           FROM wiki_pages
           WHERE path = ANY($1::text[])
              OR $2 = ANY(sources)
           ORDER BY path
           LIMIT 1""",
        LEGACY_SEED_PATHS,
        seed_name,
    )
    return legacy_path


async def _write_seed_marker(seed_name: str, seed_sha256: str) -> None:
    from db import get_pool

    pool = await get_pool()
    await pool.execute(
        """INSERT INTO wiki_pages (path, title, content, sources, embedding, updated_at)
           VALUES ($1, $2, $3, $4, NULL, NOW())
           ON CONFLICT (path) DO UPDATE
           SET title = EXCLUDED.title,
               content = EXCLUDED.content,
               sources = EXCLUDED.sources,
               updated_at = NOW()""",
        SEED_MARKER_PATH,
        "Public Aggasys Knowledge Seed",
        (
            "# Public Aggasys Knowledge Seed\n\n"
            f"Seed SHA256: {seed_sha256}\n\n"
            "This marker records that the public Aggasys company-basics seed "
            "has been loaded for this exact seed content. The deploy workflow "
            "should not re-run the DeepSeek wiki compiler for this seed unless "
            "the seed content changes or the loader is invoked with `--force`."
        ),
        [seed_name],
    )


async def _ingest(seed_path: Path, force: bool = False) -> tuple[list[str], str | None]:
    from db import close_pool
    from embedding import close_client as close_embedding_client
    from model_client import close_client as close_model_client
    from wiki import ingest_document

    text = seed_path.read_text(encoding="utf-8")
    seed_sha256 = _seed_hash(text)
    locked = False
    try:
        locked = await _try_seed_lock()
        if not locked:
            return [], "another_seed_ingest_is_running"

        existing_path = None if force else await _seed_already_loaded(seed_path.name, seed_sha256)
        if existing_path:
            await _write_seed_marker(seed_path.name, seed_sha256)
            return [], existing_path

        updated = await ingest_document(text, seed_path.name)
        if updated:
            await _write_seed_marker(seed_path.name, seed_sha256)
        return updated, None
    finally:
        if locked:
            await _release_seed_lock()
        await close_model_client()
        await close_embedding_client()
        await close_pool()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load public Aggasys basics into Gray's wiki."
    )
    parser.add_argument(
        "--seed",
        default=str(SEED_PATH),
        help="Markdown seed file to ingest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the seed path and basic environment status without ingesting.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run the DeepSeek wiki compiler even if this seed was already loaded.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    seed_path = Path(args.seed).resolve()
    if not seed_path.exists():
        print(f"Seed file not found: {seed_path}")
        return 1

    has_database = bool(os.getenv("DATABASE_URL"))
    provider = os.getenv("MODEL_PROVIDER", "")
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))

    if args.dry_run:
        print(f"Seed: {seed_path}")
        print(f"DATABASE_URL set: {has_database}")
        print(f"MODEL_PROVIDER: {provider or '(unset)'}")
        print(f"DEEPSEEK_API_KEY set: {has_deepseek}")
        return 0

    missing = []
    if not has_database:
        missing.append("DATABASE_URL")
    if provider != "deepseek":
        missing.append("MODEL_PROVIDER=deepseek")
    if not has_deepseek:
        missing.append("DEEPSEEK_API_KEY")
    if missing:
        print("Cannot ingest yet. Missing/invalid environment: " + ", ".join(missing))
        return 1

    _load_bot_modules()
    updated, skipped_existing_path = asyncio.run(_ingest(seed_path, force=args.force))
    if skipped_existing_path:
        if skipped_existing_path == "another_seed_ingest_is_running":
            print("Another public seed ingest is already running; skipping this run.")
            return 0
        print(
            "Public Aggasys company-basics seed already loaded; "
            f"skipping DeepSeek ingest. Existing marker/page: {skipped_existing_path}"
        )
        print("Use --force to regenerate wiki pages from the seed.")
        return 0

    if not updated:
        print("No wiki pages were updated.")
        return 1

    print("Updated wiki pages:")
    for path in updated:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
