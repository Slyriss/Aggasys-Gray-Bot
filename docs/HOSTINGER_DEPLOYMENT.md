# Hostinger Deployment Checklist

This repo is not deployment-ready until every item below is true on the target
Hostinger VPS or Sean's Ubuntu VM. Gray depends on Telegram, Postgres with
pgvector, Redis, a model provider such as DeepSeek API, and the Hermes scheduler
running inside the bot process.

## Server Prerequisites

- Ubuntu VM with Docker, the Docker Compose plugin, Python 3, rsync, and curl
  available.
- Enough RAM for Docker, Postgres, Redis, and the bot. Sean's current
  8 vCPU / 16 GB / 200 GB VM is comfortable for the DeepSeek API pilot.
- Ports restricted by firewall. Postgres and Redis should not be publicly open.
- SSH access with a non-root deploy user.
- System time and timezone correct. Hermes uses `HERMES_TIMEZONE`.
- DeepSeek API key available in `.env`. Ollama is optional only if
  `MODEL_PROVIDER=ollama` or `EMBEDDING_PROVIDER=ollama`.
- Postgres and Redis must report healthy in Docker Compose before the bot starts.

On the VPS, run the non-destructive prerequisite check before the first deploy
and whenever the server image changes:

```bash
bash scripts/check_vps_prereqs.sh
```

For local or VPS-side validation without mutating system Python packages, use:

```bash
python3 scripts/check_in_venv.py
```

For the standard non-destructive release gate bundle, use:

```bash
python3 scripts/release_readiness.py
# add --include-heavy and --include-docker when those slower/external gates are available
```

## Required Files

- `.env` created from `.env.example`.
- `docker-compose.yml`
- `init.sql`
- `migration.sql`
- `bot/`
- `deploy.sh`

## Required Environment

Run this before deploying:

```bash
python3 scripts/release_readiness.py
python3 scripts/check_hostinger_readiness.py
bash scripts/check_vps_prereqs.sh
python3 scripts/check_in_venv.py
python3 bot/preflight.py --env-file .env
python3 scripts/run_checks.py
python3 scripts/scan_secret_hygiene.py
python3 scripts/verify_runtime_assets.py
python3 scripts/verify_schema_assets.py
python3 scripts/verify_policy_registry.py
python3 scripts/runtime_import_smoke.py
# optional, slower speech stack check:
python3 scripts/runtime_import_smoke.py --include-heavy
# optional, network/cache dependent dependency resolver check:
python3 scripts/check_requirements_resolution.py
docker compose config >/dev/null
python3 scripts/docker_build_smoke.py
```

The preflight must report `Status: OK`.
The secret hygiene scan must report `Secret hygiene scan OK`; do not deploy
from a workspace that contains a real `.env` or committed-looking credentials.

Minimum required keys:

- `TELEGRAM_TOKEN`
- `ALLOWED_USERS`
- `ADMIN_USERS`
- `OPERATOR_USERS` (optional; admins are operators automatically)
- `DB_PASS`
- `DATABASE_URL`
- `MODEL_PROVIDER`
- `DEEPSEEK_API_KEY` when `MODEL_PROVIDER=deepseek`
- `DEEPSEEK_BASE_URL` when `MODEL_PROVIDER=deepseek`
- `DEEPSEEK_MODEL` when `MODEL_PROVIDER=deepseek`
- `EMBEDDING_PROVIDER`
- `HERMES_TIMEZONE`
- `HERMES_GROUP_CHAT_MODE`
- `HERMES_BACKUP_RETENTION_DAYS`
- `HERMES_AUDIT_RETENTION_DAYS`
- `HERMES_OPERATION_RETENTION_DAYS`
- `GRAY_BOT_USERNAME`
- `RATE_LIMIT_MESSAGES`
- `RATE_LIMIT_WINDOW_SECONDS`
- `MAX_DOCUMENT_BYTES`
- `MAX_VOICE_BYTES`
- `MAX_PHOTO_BYTES`

`DB_PASS` must match the password embedded in `DATABASE_URL`. URL-encode special
characters in `DATABASE_URL` if your generated password contains symbols.
Hermes scheduled jobs auto-pause after `HERMES_JOB_FAILURE_LIMIT` consecutive
failures; default is `3`. Auto-pauses are written to Hermes audit as
`scheduled_job_auto_paused`.
Hermes operational backups are pruned by `HERMES_BACKUP_RETENTION_DAYS`;
default is `30`.
Old Hermes audit rows can be pruned after `HERMES_AUDIT_RETENTION_DAYS`;
resolved approvals, inactive jobs, and closed standups use
`HERMES_OPERATION_RETENTION_DAYS`. Defaults are `180` and `365`.
Telegram documents, voice notes, and photos are rejected before download if they
exceed `MAX_DOCUMENT_BYTES`, `MAX_VOICE_BYTES`, or `MAX_PHOTO_BYTES`.

## Model Backend

For the DeepSeek API pilot, use:

```env
MODEL_PROVIDER=deepseek
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
EMBEDDING_PROVIDER=disabled
```

This mode does not require local model hosting, Ollama, or a GPU. Gray will use
database text search and wiki full-text search when embeddings are disabled.

Optional local embeddings can be enabled later with:

```env
EMBEDDING_PROVIDER=ollama
OLLAMA_URL=http://host.docker.internal:11434
EMBED_MODEL=nomic-embed-text
```

Do not use `http://localhost:11434` inside the bot container unless Ollama is
running in that same container.

## Database

Fresh installs use `init.sql`.

Existing installs must run:

```bash
bash scripts/backup_hermes_data.sh backups
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U aggasys -d aggasys < migration.sql
```

The migration is written to be idempotent and should run on every upgrade.
Do not skip it just because an older table already exists; Hermes tables and
columns may have been added after the older second-brain migration.
Hermes operational backups are written to `backups/hermes-<timestamp>.sql`
before upgrade migrations. Older `hermes-*.sql` files in that directory are
pruned after successful backup according to `HERMES_BACKUP_RETENTION_DAYS`.
The backup and restore scripts wait for Postgres readiness and run SQL with
`ON_ERROR_STOP=1`; do not restore a file unless it was produced by
`scripts/backup_hermes_data.sh`.

Operational retention is explicit and dry-run-first:

```bash
python3 scripts/prune_hermes_data.py
python3 scripts/prune_hermes_data.py --yes
```

Run the dry run first and review the counts before using `--yes`.

## First Deploy

```bash
python3 scripts/check_hostinger_readiness.py
bash scripts/check_vps_prereqs.sh
python3 scripts/create_env_from_example.py
# edit .env: TELEGRAM_TOKEN, ALLOWED_USERS, ADMIN_USERS, GRAY_BOT_USERNAME, and any model changes
python3 scripts/release_readiness.py --include-heavy
python3 scripts/check_in_venv.py
python3 bot/preflight.py --env-file .env
python3 scripts/run_checks.py
python3 scripts/check_requirements_resolution.py
python3 scripts/runtime_import_smoke.py --include-heavy
docker compose config >/dev/null
python3 scripts/docker_build_smoke.py
bash deploy.sh fresh
```

## Upgrade Deploy

```bash
git pull
python3 scripts/check_hostinger_readiness.py
bash scripts/check_vps_prereqs.sh
python3 scripts/release_readiness.py --include-heavy
python3 scripts/check_in_venv.py
python3 bot/preflight.py --env-file .env
python3 scripts/run_checks.py
python3 scripts/check_requirements_resolution.py
python3 scripts/runtime_import_smoke.py --include-heavy
docker compose config >/dev/null
python3 scripts/docker_build_smoke.py
bash deploy.sh upgrade
```

`deploy.sh` and the self-hosted deploy workflow also run these gates before
database migration or container rebuild. A failed migration must stop deploy.

Hermes policy is registry-gated. When adding a new `_decide_and_audit(...)`
action or tool in `TOOLS_SCHEMA`, register it in `bot/hermes/policy.py`;
`scripts/verify_policy_registry.py` fails deploy checks if the registry drifts.

## Post-Deploy Checks

```bash
bash scripts/check_post_deploy_health.sh
docker compose ps
docker compose logs bot --tail=100
```

Run the full Telegram checklist in `docs/TELEGRAM_SMOKE_TEST.md`.

In Telegram:

- `/start`
- `/hermes_status`
- `/ops_status`
- `/forget_me`
- `/standup_schedule 09:30 Alice, Bob`
- `/standup_chase_schedule 09:50`
- `/monitor_schedule 10:00 Singapore SME AI tenders`
- `/standup_chase`
- `/schedules`
- `/schedule_pause <id>`
- `/schedule_resume <id>`
- `/schedule_remove <id>`

Expected:

- Bot replies to `/start`.
- `bash scripts/check_post_deploy_health.sh` reports `Post-deploy health check OK`.
- `docker compose ps` shows Postgres and Redis as healthy.
- `/hermes_status` shows scheduler `running`.
- `/ops_status` shows redacted model, role, rate-limit, upload-limit, backup,
  scheduler, and approval state without exposing tokens or API keys.
- `/forget_me` previews personal data counts and asks for exact confirmation;
  do not run `/forget_me CONFIRM` unless deleting that account's personal Gray
  data is intended.
- `/schedules` shows the daily standup, chase, and monitor jobs.
- `/standup_chase` reminds only missing participants when a standup is open.
- The monitor posts read-only web search results at the scheduled time.
- Pause, resume, and remove should update the schedule state without errors.
- Repeatedly failing schedules auto-pause after `HERMES_JOB_FAILURE_LIMIT`.
- In group chats, ordinary messages should not trigger Gray unless
  `HERMES_GROUP_CHAT_MODE=all`; mention `@<GRAY_BOT_USERNAME>` or reply to Gray.

## Rollback

```bash
git checkout <previous-good-commit>
bash deploy.sh upgrade
docker compose logs bot --tail=100
```

Database migrations are additive in the current Hermes build. Do not drop
Hermes tables during rollback unless you have exported audit and schedule data.
Use the newest `backups/hermes-*.sql` file if Hermes operational data needs to
be restored after a failed upgrade.

To restore Hermes operational data explicitly:

```bash
docker compose stop bot
bash scripts/restore_hermes_data.sh backups/hermes-<timestamp>.sql --yes
docker compose up -d bot
```

## Current Limits

- Hermes scheduler is in-process. It is safe for a single bot service and uses
  job claiming to reduce duplicate runs, but we should still run one bot
  replica until we add stronger distributed scheduler leadership.
- Approval requests are durable, but approved actions are not yet resumed
  automatically. The approval layer is ready for future admin workflows.
- Supply ordering is intentionally not implemented yet.
