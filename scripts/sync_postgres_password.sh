#!/usr/bin/env bash
# Align the existing Postgres role password with the deployment .env.

set -euo pipefail

ENV_FILE=${1:-.env}

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  exit 1
fi

DB_PASS_VALUE="$(
  python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("DB_PASS="):
        print(line.split("=", 1)[1])
        break
PY
)"

if [ -z "${DB_PASS_VALUE:-}" ]; then
  echo "DB_PASS is missing from $ENV_FILE" >&2
  exit 1
fi

DB_PASS_VALUE="$DB_PASS_VALUE" python3 - <<'PY' \
  | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U aggasys -d aggasys >/dev/null
import os

password = os.environ["DB_PASS_VALUE"]
print("ALTER USER aggasys WITH PASSWORD '" + password.replace("'", "''") + "';")
PY

echo "Postgres role password aligned with deployment env."
