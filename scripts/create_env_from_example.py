from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PASSWORD_BYTES = 24


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local .env from .env.example with a strong DB password.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing .env.")
    parser.add_argument("--db-pass", help="Use a specific DB_PASS instead of generating one.")
    args = parser.parse_args()

    env_path = ROOT / ".env"
    example_path = ROOT / ".env.example"
    if env_path.exists() and not args.force:
        print(".env already exists. Use --force only if you intentionally want to replace it.", file=sys.stderr)
        return 1
    if not example_path.exists():
        print(".env.example is missing.", file=sys.stderr)
        return 1

    db_pass = args.db_pass or secrets.token_urlsafe(DEFAULT_PASSWORD_BYTES)
    if len(db_pass) < 16:
        print("DB password must be at least 16 characters.", file=sys.stderr)
        return 1

    rendered = _render_env(example_path.read_text(encoding="utf-8"), db_pass)
    env_path.write_text(rendered, encoding="utf-8")

    print("Created .env with a generated DB_PASS and matching DATABASE_URL.")
    print("Next: edit TELEGRAM_TOKEN, ALLOWED_USERS, and GRAY_BOT_USERNAME, then run:")
    print("  python3 bot/preflight.py --env-file .env")
    return 0


def _render_env(template: str, db_pass: str) -> str:
    encoded = quote(db_pass, safe="")
    lines: list[str] = []
    for line in template.splitlines():
        if line.startswith("DB_PASS="):
            lines.append(f"DB_PASS={db_pass}")
        elif line.startswith("DATABASE_URL="):
            lines.append(f"DATABASE_URL=postgresql://aggasys:{encoded}@postgres:5432/aggasys")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
