# Aggasys Gray Bot

Gray is a Telegram-based AI operations teammate for Aggasys. The current build
adds a Hermes-style control harness around the bot so it can behave more like a
careful internal teammate: useful in group chats, explicit about what it can do,
and guarded around actions that could spend money, alter external systems, or
touch sensitive admin workflows.

Supply ordering is intentionally not implemented yet.

## What Gray Can Do

- Answer company-context questions through the existing memory and retrieval
  tools.
- Run standups, collect updates, chase missing teammates, and post summaries.
- Schedule daily standups, standup chases, and read-only web monitoring jobs.
- Gate risky actions behind Hermes policy and approval records.
- Ignore ordinary group-chat chatter unless mentioned or replied to, depending
  on `HERMES_GROUP_CHAT_MODE`.
- Handle text, voice, documents, and photos through the existing Telegram bot
  surface.

## Architecture

- `bot/main.py` owns the Telegram command and message handlers.
- `bot/agent.py` routes user requests to allowed tools.
- `bot/tools.py` exposes the current read-only tool surface.
- `bot/hermes/` contains policy, guardrails, approvals, standup workflows,
  monitoring helpers, and the in-process scheduler.
- `init.sql` and `migration.sql` create the memory, audit, approval, schedule,
  and standup tables.
- `docker-compose.yml` runs the bot with Postgres/pgvector and Redis.

## Local Checks

Run the standard gate:

```bash
python scripts/run_checks.py
```

For a fuller release pass:

```bash
python scripts/release_readiness.py
```

Useful optional checks:

```bash
python scripts/check_requirements_resolution.py
python scripts/check_in_venv.py
python scripts/runtime_import_smoke.py --include-heavy
python scripts/docker_build_smoke.py
```

`scripts/scan_secret_hygiene.py` is part of `run_checks.py`. It fails if a real
`.env`, Telegram bot token, or concrete database/API secret appears in the repo
workspace.

## Environment

Create a local `.env` only from the template, and never commit it:

```bash
python scripts/create_env_from_example.py
```

Then edit `.env` with the real Telegram token, allowed Telegram user IDs, bot
username, and DeepSeek API key. Validate it with:

```bash
python bot/preflight.py --env-file .env
```

For Sean's Ubuntu VM pilot, keep:

```env
MODEL_PROVIDER=deepseek
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
EMBEDDING_PROVIDER=disabled
```

## Deployment Timing

The best time to deploy is after all of these are true on the target Hostinger
VPS:

- `python scripts/release_readiness.py --include-heavy --include-docker` passes.
- `python bot/preflight.py --env-file .env` reports `Status: OK`.
- `bash scripts/check_vps_prereqs.sh` passes. In DeepSeek mode, Ollama is not
  required.
- `docker compose config` and `python scripts/docker_build_smoke.py` pass on the
  VPS.
- You have a real Telegram bot token, `ALLOWED_USERS`, `ADMIN_USERS`, and
  `GRAY_BOT_USERNAME`.
- You are ready to run the Telegram smoke test in `docs/TELEGRAM_SMOKE_TEST.md`
  immediately after deploy.

Practically: deploy during a quiet operations window when the team can tolerate
Telegram bot downtime for 15-30 minutes and at least one admin is available to
test commands in Telegram. Do not deploy right before a standup, demo, client
call, payroll/admin deadline, or supplier/order workflow.

## Hostinger Deployment

Use the full runbook:

```bash
docs/HOSTINGER_DEPLOYMENT.md
```

Fresh install:

```bash
bash deploy.sh fresh
```

Upgrade:

```bash
bash deploy.sh upgrade
```

Both deploy paths run preflight checks, local gates, database backup/migration,
container startup, and post-deploy health checks.

## Access Roles

- `ALLOWED_USERS` can chat with Gray and use personal/task/read commands.
- `OPERATOR_USERS` can run team workflow commands such as standup scheduling,
  standup chasing, and standup closing.
- `ADMIN_USERS` can approve/deny Hermes requests, manage schedules, run web
  monitoring, and change wiki knowledge. Admins automatically count as
  operators.
- `/ops_status` gives admins a redacted runtime view of model, role, rate-limit,
  upload-limit, backup, scheduler, and approval state without exposing secrets.
- Unhandled Telegram handler failures are caught by a global error boundary,
  replied to generically, and audited as `telegram_handler_error` with status
  `handler_error` without storing exception text.
- URL reading rejects localhost, private/link-local IPs, unsafe DNS resolutions,
  private redirects, oversized responses, and non-HTTP(S) schemes before content
  is injected into Gray's context.
- `RATE_LIMIT_MESSAGES` and `RATE_LIMIT_WINDOW_SECONDS` cap allowed-user traffic
  before model/database work starts. Rate-limit denials are written to Hermes
  audit as `rate_limited` with status `blocked_rate_limit`.
- `MAX_DOCUMENT_BYTES`, `MAX_VOICE_BYTES`, and `MAX_PHOTO_BYTES` reject large
  Telegram uploads before download/model work. Oversize denials are written to
  Hermes audit as `upload_too_large:<kind>` with status `blocked_upload_size`.

## Current Limits

- Run one bot replica until scheduler leadership is stronger.
- Approval records are durable, but approved side-effect workflows are not yet
  auto-resumed.
- Supply ordering remains out of scope for now.
- Local Docker build smoke requires Docker Desktop or a reachable Docker engine.
- DeepSeek mode requires a valid `DEEPSEEK_API_KEY` in `.env`.
