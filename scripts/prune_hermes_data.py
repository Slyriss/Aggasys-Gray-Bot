from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run or prune old Gray/Hermes operational data."
    )
    parser.add_argument(
        "--audit-days",
        type=positive_int,
        default=int(os.getenv("HERMES_AUDIT_RETENTION_DAYS", "180")),
        help="Keep Hermes audit rows for this many days.",
    )
    parser.add_argument(
        "--operation-days",
        type=positive_int,
        default=int(os.getenv("HERMES_OPERATION_RETENTION_DAYS", "365")),
        help="Keep resolved approvals, removed/paused jobs, and closed standups for this many days.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete eligible rows. Without this flag the script is a dry run.",
    )
    return parser


async def main_async(args: argparse.Namespace) -> int:
    from db import get_hermes_retention_counts, prune_hermes_retention

    counts = await get_hermes_retention_counts(
        audit_days=args.audit_days,
        operation_days=args.operation_days,
    )
    if not args.yes:
        print("Hermes retention dry run")
        print(f"Audit retention days: {args.audit_days}")
        print(f"Operational retention days: {args.operation_days}")
        print_counts(counts)
        print("No rows deleted. Re-run with --yes to prune.")
        return 0

    deleted = await prune_hermes_retention(
        audit_days=args.audit_days,
        operation_days=args.operation_days,
    )
    print("Hermes retention prune completed")
    print(f"Audit retention days: {args.audit_days}")
    print(f"Operational retention days: {args.operation_days}")
    print_counts(deleted)
    return 0


def print_counts(counts: dict) -> None:
    print(f"Audit rows: {counts.get('audit_log', 0)}")
    print(f"Resolved approvals: {counts.get('approval_requests', 0)}")
    print(f"Removed/paused jobs: {counts.get('jobs', 0)}")
    print(f"Closed standups: {counts.get('standup_sessions', 0)}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
