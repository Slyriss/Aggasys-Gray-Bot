from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SKIPPED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    ".venv-smoke",
    "__pycache__",
    "backups",
    "node_modules",
}

SKIPPED_SUFFIXES = {
    ".7z",
    ".db",
    ".dll",
    ".exe",
    ".gz",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".png",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".tar",
    ".webp",
    ".whl",
    ".zip",
}

SECRET_ASSIGNMENT_RE = re.compile(
    r"^(TELEGRAM_TOKEN|DB_PASS|DATABASE_URL|REDIS_URL|OPENAI_API_KEY|"
    r"ANTHROPIC_API_KEY|DEEPSEEK_API_KEY|GITHUB_TOKEN|HERMES_API_KEY)=(.+?)\s*$"
)
TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
POSTGRES_URL_RE = re.compile(r"postgres(?:ql)?://[^:\s/@]+:([^@\s]+)@[^)\]\s'\"`]+")

PLACEHOLDER_MARKERS = (
    "<",
    ">",
    "...",
    "changeme",
    "dummy",
    "example",
    "placeholder",
    "replace",
    "sample",
    "your_",
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str

    def render(self, root: Path) -> str:
        try:
            rel = self.path.relative_to(root)
        except ValueError:
            rel = self.path
        return f"{rel}:{self.line}: {self.message}"


def main() -> int:
    findings = scan_repository(ROOT)
    if findings:
        print("Secret hygiene scan failed:")
        for finding in findings:
            print(f"- {finding.render(ROOT)}")
        return 1
    print("Secret hygiene scan OK")
    return 0


def scan_repository(root: Path) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    env_path = root / ".env"
    if env_path.exists():
        findings.append(Finding(env_path, 1, "Real .env file must not be present in the repository workspace."))

    for path in _iter_text_files(root):
        if path == env_path:
            continue
        findings.extend(_scan_file(root, path))
    return findings


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & SKIPPED_DIRS:
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        yield path


def _scan_file(root: Path, path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings

    for line_number, line in enumerate(text.splitlines(), start=1):
        assignment = SECRET_ASSIGNMENT_RE.match(line)
        if assignment:
            key, value = assignment.groups()
            if _is_real_secret_value(value):
                findings.append(Finding(path, line_number, f"{key} contains a non-placeholder secret value."))

        for token in TELEGRAM_TOKEN_RE.findall(line):
            if _is_real_secret_value(token):
                findings.append(Finding(path, line_number, "Real-looking Telegram bot token found."))

        for password in POSTGRES_URL_RE.findall(line):
            if _is_real_secret_value(password):
                findings.append(Finding(path, line_number, "Database URL contains a non-placeholder password."))

    return findings


def _is_real_secret_value(value: str) -> bool:
    normalized = value.strip().strip("'\"`").lower()
    if not normalized:
        return False
    if normalized in {"none", "null", "false"}:
        return False
    if any(marker in value for marker in ("{", "}", "$(", "${", "+")):
        return False
    return not any(marker in normalized for marker in PLACEHOLDER_MARKERS)


if __name__ == "__main__":
    raise SystemExit(main())
