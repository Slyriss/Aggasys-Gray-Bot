"""Ingest the public Aggasys company-basics seed into Gray's wiki.

Requires a configured .env with DATABASE_URL and DeepSeek model settings.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
SEED_PATH = ROOT / "docs" / "AGGASYS_PUBLIC_KNOWLEDGE_SEED.md"


def _load_bot_modules() -> None:
    sys.path.insert(0, str(BOT_DIR))


async def _ingest(seed_path: Path) -> list[str]:
    from db import close_pool
    from embedding import close_client as close_embedding_client
    from model_client import close_client as close_model_client
    from wiki import ingest_document

    text = seed_path.read_text(encoding="utf-8")
    try:
        return await ingest_document(text, seed_path.name)
    finally:
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
    updated = asyncio.run(_ingest(seed_path))
    if not updated:
        print("No wiki pages were updated.")
        return 1

    print("Updated wiki pages:")
    for path in updated:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
