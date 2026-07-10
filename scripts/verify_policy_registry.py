from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from hermes import HermesPolicy  # noqa: E402


def main() -> int:
    errors: list[str] = []
    policy = HermesPolicy()

    for action_name in sorted(_constant_audit_actions(ROOT / "bot" / "main.py")):
        if not policy._is_registered_action(action_name):
            errors.append(f"Unregistered Hermes audit action in bot/main.py: {action_name}")

    for prefix in sorted(_dynamic_audit_prefixes(ROOT / "bot" / "main.py")):
        if not policy._is_read_only(prefix):
            errors.append(f"Unregistered Hermes audit action prefix in bot/main.py: {prefix}")

    for tool_name in sorted(_tool_schema_names(ROOT / "bot" / "tools.py")):
        if not policy._is_registered_action(tool_name):
            errors.append(f"Tool is not registered in Hermes policy: {tool_name}")
        if tool_name not in policy.READ_ONLY_ACTIONS:
            errors.append(f"Tool should be explicitly read-only in Hermes policy: {tool_name}")

    if errors:
        print("Hermes policy registry verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Hermes policy registry verification OK")
    return 0


def _constant_audit_actions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for call in _audit_calls(tree):
        if len(call.args) < 2:
            continue
        action_arg = call.args[1]
        if isinstance(action_arg, ast.Constant) and isinstance(action_arg.value, str):
            names.add(action_arg.value)
    return names


def _dynamic_audit_prefixes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefixes: set[str] = set()
    for call in _audit_calls(tree):
        if len(call.args) < 2:
            continue
        action_arg = call.args[1]
        if isinstance(action_arg, ast.JoinedStr):
            first_part = action_arg.values[0] if action_arg.values else None
            if isinstance(first_part, ast.Constant) and isinstance(first_part.value, str):
                prefixes.add(first_part.value)
    return prefixes


def _audit_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "_decide_and_audit":
            calls.append(node)
    return calls


def _tool_schema_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "TOOLS_SCHEMA" for target in node.targets):
            continue
        schema = ast.literal_eval(node.value)
        return {item["name"] for item in schema if isinstance(item, dict) and "name" in item}
    return set()


if __name__ == "__main__":
    raise SystemExit(main())
