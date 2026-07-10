#!/bin/bash
# Back up Hermes operational tables before upgrade migrations.

set -euo pipefail

BACKUP_DIR=${1:-backups}
BACKUP_RETENTION_DAYS=${HERMES_BACKUP_RETENTION_DAYS:-30}
STAMP=$(date -u +"%Y%m%dT%H%M%SZ")
OUT="$BACKUP_DIR/hermes-$STAMP.sql"

TABLES=(
  hermes_audit_log
  hermes_approval_requests
  hermes_jobs
  standup_sessions
)

mkdir -p "$BACKUP_DIR"

if ! [[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || [ "$BACKUP_RETENTION_DAYS" -lt 1 ]; then
  echo "HERMES_BACKUP_RETENTION_DAYS must be a positive integer." >&2
  exit 1
fi

docker compose up -d postgres

for attempt in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U aggasys -d aggasys >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "Postgres did not become ready in time for Hermes backup." >&2
    exit 1
  fi
  sleep 2
done

existing_tables=$(docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U aggasys -d aggasys -tAc \
  "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('hermes_audit_log','hermes_approval_requests','hermes_jobs','standup_sessions') ORDER BY tablename;")

if [ -z "${existing_tables//[[:space:]]/}" ]; then
  echo "No Hermes tables found yet; skipping Hermes data backup."
  exit 0
fi

args=()
for table in "${TABLES[@]}"; do
  if echo "$existing_tables" | grep -qx "$table"; then
    args+=(--table="$table")
  fi
done

docker compose exec -T postgres pg_dump -U aggasys -d aggasys \
  --data-only \
  --column-inserts \
  "${args[@]}" > "$OUT"

if [ ! -s "$OUT" ]; then
  echo "Hermes backup file was not written or is empty: $OUT" >&2
  exit 1
fi

if ! grep -q "PostgreSQL database dump" "$OUT"; then
  echo "Hermes backup file does not look like a pg_dump output: $OUT" >&2
  exit 1
fi

echo "Hermes data backup written to $OUT"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'hermes-*.sql' -mtime +"$BACKUP_RETENTION_DAYS" -print -delete \
  | sed 's/^/Pruned old Hermes backup: /'
