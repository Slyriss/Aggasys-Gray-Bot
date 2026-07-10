# Gray User Guide

Gray is the Aggasys Telegram operations teammate. Use it in private chat for
personal memory/tasks, and in team groups for standups, schedules, knowledge
lookup, and admin workflows.

## Roles

Gray has three practical access tiers.

| Tier | Who | Can do |
| --- | --- | --- |
| Member | IDs in `ALLOWED_USERS` | Chat with Gray, ask company questions, add notes/tasks, post standup updates, read standup status. |
| Operator | IDs in `OPERATOR_USERS` plus admins | Start, chase, close, and schedule standup workflows. |
| Admin | IDs in `ADMIN_USERS` | Approve/deny Hermes actions, manage schedules, ingest/lint company knowledge, run ops status, schedule web monitors. |

Admins automatically count as operators. Unknown users are ignored when
`ALLOWED_USERS` is set.

## Daily Use

### Ask Gray Questions

Send a normal message in private chat, or mention Gray in a group:

```text
@Gray what is our pricing for support retainers?
@Gray find the Notion playbook for onboarding
```

### Notes And Recall

```text
/note Client ABC prefers Monday renewals
/recall ABC renewals
/memory
```

### Personal Tasks

```text
/task Follow up with ABC by Friday
/tasks
/done 12
/brief
```

## Automated Standups

The recommended setup is to configure the schedule once, then let Gray run it
daily.

### One-Time Setup

Run these in the team Telegram group from an operator/admin account:

```text
/standup_schedule 09:30 Alice, Bob, Charlie
/standup_chase_schedule 09:50
/standup_summary_schedule 17:30 both
```

What happens after setup:

- At `09:30`, Gray opens or reuses the daily standup and prompts the team.
- Team members post updates with `/standup_update <yesterday / today / blockers>`.
- At `09:50`, Gray reminds only missing participants.
- At `17:30`, Gray closes the open standup and sends a summary.

### Summary Recipients

`/standup_summary_schedule` supports three recipient tiers:

```text
/standup_summary_schedule 17:30 chat
/standup_summary_schedule 17:30 admins
/standup_summary_schedule 17:30 both
```

- `chat`: post the final summary back to the group.
- `admins`: DM the summary to Telegram IDs in `ADMIN_USERS`.
- `both`: post to the group and DM admins.

Admins must have started a private chat with Gray before Telegram allows Gray to
DM them.

### During The Day

Members:

```text
/standup_update Yesterday shipped X. Today doing Y. Blocked by Z.
/standup_status
```

Operators/admins:

```text
/standup_chase
/standup_close
```

Manual close is optional when `/standup_summary_schedule` is configured.

## Schedules

View and manage scheduled jobs:

```text
/schedules
/schedule_pause <id>
/schedule_resume <id>
/schedule_remove <id>
```

Only admins can pause, resume, or remove schedules.

If the same daily schedule already exists in the chat, Gray will reuse it and
show the existing schedule ID instead of creating a duplicate recurring job.

## Company Knowledge

Admins can update the wiki:

```text
/ingest <text or URL>
/lint
/wiki
```

Members can read/search knowledge through normal chat and `/recall`.

## Admin Operations

```text
/ops_status
/hermes_status
/hermes
/approvals
/approve <id>
/deny <id> <reason>
```

`/ops_status` is redacted. It shows whether secrets are set, but never prints
the secret values.

## Privacy And Safety

```text
/forget_me
/forget_me CONFIRM
```

`/forget_me` previews what Gray stores for your Telegram ID. The `CONFIRM`
variant deletes personal Gray data and anonymizes company-memory source links.

Gray rate-limits allowed users, blocks oversized uploads, audits restricted
actions, and ignores normal group chatter unless group-chat policy says it
should respond.
