from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SMOKE_REQUIRED_COMMANDS = {
    "approvals",
    "approve",
    "deny",
    "hermes",
    "hermes_status",
    "monitor_schedule",
    "ops_status",
    "schedule_pause",
    "schedule_resume",
    "schedule_remove",
    "schedules",
    "standup_chase",
    "standup_chase_schedule",
    "standup_close",
    "standup_schedule",
    "standup_start",
    "standup_status",
    "standup_update",
}

FORBIDDEN_COMMANDS = {"supply_order"}


def main() -> int:
    main_py = (ROOT / "bot" / "main.py").read_text(encoding="utf-8")
    smoke = (ROOT / "docs" / "TELEGRAM_SMOKE_TEST.md").read_text(encoding="utf-8")
    errors: list[str] = []

    registered = _registered_commands(main_py)
    help_commands = _slash_commands(_function_string_literals(main_py, "start"))
    smoke_commands = _slash_commands(smoke)

    undocumented = sorted(registered - help_commands)
    if undocumented:
        errors.append("Registered commands missing from /start help: " + ", ".join(undocumented))

    stale_help = sorted((help_commands - registered) - {"help"})
    if stale_help:
        errors.append("/start help mentions unregistered commands: " + ", ".join(stale_help))

    missing_smoke = sorted(SMOKE_REQUIRED_COMMANDS - smoke_commands)
    if missing_smoke:
        errors.append("Telegram smoke test missing Hermes commands: " + ", ".join(missing_smoke))

    forbidden = sorted((registered | help_commands | smoke_commands) & FORBIDDEN_COMMANDS)
    if forbidden:
        errors.append("Forbidden commands are still exposed: " + ", ".join(forbidden))

    if errors:
        print("Command surface verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Command surface verification OK")
    return 0


def _registered_commands(source: str) -> set[str]:
    tree = ast.parse(source)
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "CommandHandler":
            continue
        if not node.args:
            continue
        command_arg = node.args[0]
        if isinstance(command_arg, ast.Constant) and isinstance(command_arg.value, str):
            commands.add(command_arg.value)
    return commands


def _function_string_literals(source: str, function_name: str) -> str:
    tree = ast.parse(source)
    parts: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                parts.append(child.value)
    return "\n".join(parts)


def _slash_commands(text: str) -> set[str]:
    return set(re.findall(r"(?<![\w/])\/([a-z][a-z0-9_]+)", text))


if __name__ == "__main__":
    raise SystemExit(main())
