#!/bin/bash
# Restore Hermes operational data from a backup created by backup_hermes_data.sh.

set -euo pipefail

BACKUP_FILE=${1:-}
CONFIRM=${2:-}

if [ -z "$BACKUP_FILE" ] || [ "$CONFIRM" != "--yes" ]; then
  echo "Usage: bash scripts/restore_hermes_data.sh backups/hermes-YYYYMMDDTHHMMSSZ.sql --yes"
  echo "This restores Hermes operational rows into the current database."
  exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if ! grep -q "INSERT INTO" "$BACKUP_FILE"; then
  echo "Backup file does not look like a Hermes data backup: $BACKUP_FILE" >&2
  exit 1
fi

if ! grep -Eq "INSERT INTO (public\.)?(hermes_audit_log|hermes_approval_requests|hermes_jobs|standup_sessions)" "$BACKUP_FILE"; then
  echo "Backup file does not contain Hermes operational table inserts: $BACKUP_FILE" >&2
  exit 1
fi

docker compose up -d postgres

for attempt in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U aggasys -d aggasys >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "Postgres did not become ready in time for Hermes restore." >&2
    exit 1
  fi
  sleep 2
done

docker compose exec -T postgres psql -U aggasys -d aggasys \
  -v ON_ERROR_STOP=1 \
  -c "TRUNCATE hermes_audit_log, hermes_approval_requests, hermes_jobs, standup_sessions RESTART IDENTITY CASCADE;"

docker compose exec -T postgres psql -U aggasys -d aggasys \
  -v ON_ERROR_STOP=1 < "$BACKUP_FILE"

echo "Hermes data restored from $BACKUP_FILE"
