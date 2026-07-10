from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StandupUpdate:
    participant: str
    text: str


def parse_participants(raw: str) -> list[str]:
    participants = []
    for chunk in raw.replace("\n", ",").split(","):
        name = chunk.strip().lstrip("@")
        if name and name.lower() not in {p.lower() for p in participants}:
            participants.append(name)
    return participants


def summarize_standup_updates(updates: dict[str, str], missing: list[str]) -> str:
    lines = ["Standup summary:"]
    if updates:
        for name, text in sorted(updates.items()):
            lines.append(f"- {name}: {text}")
    if missing:
        lines.append("Missing updates: " + ", ".join(missing))
    if len(lines) == 1:
        lines.append("- No updates yet.")
    return "\n".join(lines)


def missing_standup_participants(participants: list[str], updates: dict[str, str]) -> list[str]:
    updated = {name.lower() for name in updates}
    return [participant for participant in participants if participant.lower() not in updated]


def standup_chase_message(missing: list[str]) -> str:
    if not missing:
        return "All standup updates are in."
    mentions = ", ".join(_mention_name(name) for name in missing)
    return (
        f"Still waiting on standup updates from: {mentions}.\n"
        "Please post yesterday / today / blockers."
    )


def looks_like_standup_update(text: str) -> bool:
    if not text:
        return False
    lowered = text.strip().lower()
    if lowered.startswith(("standup:", "daily update:", "update:")):
        return True
    markers = {
        "yesterday": bool(re.search(r"\byesterday\b|\byday\b", lowered)),
        "today": bool(re.search(r"\btoday\b|\btdy\b", lowered)),
        "blocker": bool(re.search(r"\bblockers?\b|\bblocked\b|\bno blockers?\b", lowered)),
    }
    if sum(1 for value in markers.values() if value) >= 2:
        return True
    return bool(re.search(r"\b(done|did|shipped|finished).+\b(today|tomorrow|blocker|blocked)\b", lowered))


def _mention_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        return clean
    return clean if clean.startswith("@") else f"@{clean}"
