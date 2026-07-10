from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "DEPLOY_STATUS.md"

TELEGRAM_TOKEN_RE = re.compile(r"\bbot?\d{6,12}:[A-Za-z0-9_-]{30,}\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:TOKEN|PASSWORD|PASS|SECRET|KEY|DATABASE_URL|DB_PASS|DEEPSEEK_API_KEY)"
    r"\s*[=:]\s*(?!\*\*\*|redacted\b)[^\s`]+",
    re.IGNORECASE,
)
RUNTIME_FAILURE_MARKERS = (
    "Traceback",
    "CRITICAL",
    "ERROR:",
    "Unhandled exception",
    "SystemExit",
    "password authentication failed",
    "Hermes scheduler tick failed",
)
REQUIRED_HEALTH_MARKERS = (
    "Post-deploy health check OK",
    "MODEL_PROVIDER=deepseek",
    "EMBEDDING_PROVIDER=disabled",
    "Application started",
)


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    path = Path(args[0]) if args else STATUS_PATH
    findings = verify_status(path)
    if findings:
        print("Deploy status verification failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Deploy status verification OK")
    return 0


def verify_status(path: Path) -> list[str]:
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    findings: list[str] = []

    if TELEGRAM_TOKEN_RE.search(text):
        findings.append("DEPLOY_STATUS.md contains an unredacted Telegram bot token.")
    if SECRET_ASSIGNMENT_RE.search(text):
        findings.append("DEPLOY_STATUS.md contains an unredacted secret assignment.")

    for marker in RUNTIME_FAILURE_MARKERS:
        if marker in text:
            findings.append(f"DEPLOY_STATUS.md contains runtime failure marker: {marker}")

    for marker in REQUIRED_HEALTH_MARKERS:
        if marker not in text:
            findings.append(f"DEPLOY_STATUS.md missing health marker: {marker}")

    return findings


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
