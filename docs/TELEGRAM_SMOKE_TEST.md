# Telegram Smoke Test

Run this after a fresh or upgraded Hostinger deploy from a Telegram account in
`ADMIN_USERS`. Repeat the standup-only section from an `OPERATOR_USERS` account
when testing delegated workflow access.

## Service Checks

```bash
docker compose ps
docker compose logs bot --tail=100
python3 bot/preflight.py --env-file .env
```

Expected:

- Postgres and Redis show healthy.
- Bot logs show startup without repeated exceptions.
- Preflight reports `Status: OK`.

## Private Chat

Send these to Gray in a private chat:

```text
/start
/hermes_status
/ops_status
/note smoke test note
/recall smoke test note
/task smoke test task
/tasks
/brief
/forget_me
```

Expected:

- `/start` returns the command list.
- `/hermes_status` shows scheduler `running`.
- `/ops_status` shows redacted model, role, rate-limit, upload-limit, backup,
  scheduler, and approval state without showing API keys or tokens.
- `/forget_me` previews personal data counts and asks for exact confirmation;
  do not run `/forget_me CONFIRM` during a smoke test unless deleting that test
  account's personal Gray data is intended.
- Note, recall, task, tasks, and brief all answer without errors.

## Standup Workflow

Use a test group or private chat:

```text
/standup_start Alice, Bob
/standup_update Yesterday deployed smoke test. Today verifying Gray. No blockers.
/standup_status
/standup_chase
/standup_close
```

Expected:

- Standup opens.
- Update is recorded.
- Status shows Alice/Bob progress.
- Chase mentions only missing participants.
- Close posts a summary.

## Scheduler Workflow

Use times a few minutes in the future:

```text
/standup_schedule 09:30 Alice, Bob
/standup_chase_schedule 09:50
/monitor_schedule 10:00 Singapore SME AI tenders
/schedules
/schedule_pause <id>
/schedule_resume <id>
/schedule_remove <id>
```

Expected:

- `/schedules` lists daily standup, chase, and monitor jobs.
- Pause, resume, and remove update schedule state without errors.
- Scheduled jobs appear in `/hermes` audit after they run.
- `/monitor_schedule`, `/schedule_pause`, `/schedule_resume`, and
  `/schedule_remove` require an admin.

## Group Chat Policy

In a group where Gray is present and `HERMES_GROUP_CHAT_MODE=mention`:

```text
ordinary unmentioned message
@<GRAY_BOT_USERNAME> /hermes_status
```

Expected:

- Gray ignores the ordinary message.
- Gray responds when mentioned or when replied to.

## Approval Surface

```text
/approvals
/hermes
/approve 999999
/deny 999999 smoke
```

Expected:

- `/approvals` responds even when empty.
- `/hermes` shows recent audit entries or says none exist yet.
- Unknown approval IDs return a clear not-found or already-resolved message.
