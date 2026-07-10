from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_TABLES = {
    "hermes_audit_log": {
        "id",
        "telegram_user_id",
        "chat_id",
        "action_name",
        "risk",
        "decision",
        "status",
        "details",
        "created_at",
    },
    "hermes_approval_requests": {
        "id",
        "telegram_user_id",
        "chat_id",
        "action_name",
        "risk",
        "status",
        "prompt",
        "reason",
        "params",
        "requested_at",
        "expires_at",
        "resolved_by",
        "resolved_at",
        "resolution_note",
    },
    "hermes_jobs": {
        "id",
        "chat_id",
        "created_by",
        "job_type",
        "status",
        "schedule_kind",
        "schedule_value",
        "next_run_at",
        "last_run_at",
        "last_error",
        "consecutive_failures",
        "locked_at",
        "payload",
        "created_at",
        "updated_at",
    },
    "standup_sessions": {
        "id",
        "chat_id",
        "created_by",
        "status",
        "participants",
        "updates",
        "summary",
        "created_at",
        "completed_at",
    },
}

REQUIRED_INDEXES = {
    "idx_hermes_audit_chat_created_at",
    "idx_hermes_approvals_chat_status",
    "idx_hermes_approvals_expiry",
    "idx_hermes_jobs_due",
    "idx_hermes_jobs_chat",
    "idx_standup_sessions_chat_status",
}

REQUIRED_MIGRATION_ALTERS = {
    "ALTER TABLE hermes_approval_requests ADD COLUMN IF NOT EXISTS expires_at",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS last_error",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS consecutive_failures",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS locked_at",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS payload",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS updated_at",
}


def main() -> int:
    errors: list[str] = []

    for filename in ("init.sql", "migration.sql"):
        sql = _read(filename)
        if not sql:
            errors.append(f"Missing SQL file: {filename}")
            continue

        for table, required_columns in REQUIRED_TABLES.items():
            columns = _table_columns(sql, table)
            missing = sorted(required_columns - columns)
            if missing:
                errors.append(f"{filename} table {table} missing columns: {', '.join(missing)}")

        for index in sorted(REQUIRED_INDEXES):
            if f"CREATE INDEX IF NOT EXISTS {index}" not in sql:
                errors.append(f"{filename} missing index: {index}")

    migration = _read("migration.sql")
    for marker in sorted(REQUIRED_MIGRATION_ALTERS):
        if marker not in migration:
            errors.append(f"migration.sql missing idempotent alter: {marker}")
    _require_order(
        migration,
        "ALTER TABLE hermes_approval_requests ADD COLUMN IF NOT EXISTS expires_at",
        "CREATE INDEX IF NOT EXISTS idx_hermes_approvals_expiry",
        "migration.sql must add hermes approval expires_at before creating its index.",
        errors,
    )

    db_py = _read("bot/db.py")
    for table in REQUIRED_TABLES:
        if table not in db_py:
            errors.append(f"bot/db.py does not reference expected table: {table}")

    if errors:
        print("Schema asset verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Schema asset verification OK")
    return 0


def _read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _table_columns(sql: str, table: str) -> set[str]:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\s*\((.*?)\);",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return set()
    columns: set[str] = set()
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        name = line.split(None, 1)[0].strip('"')
        if name.upper() not in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            columns.add(name)
    return columns


def _require_order(text: str, first: str, second: str, message: str, errors: list[str]) -> None:
    first_pos = text.find(first)
    second_pos = text.find(second)
    if first_pos == -1 or second_pos == -1:
        return
    if first_pos > second_pos:
        errors.append(message)


if __name__ == "__main__":
    raise SystemExit(main())
