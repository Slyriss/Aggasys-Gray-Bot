from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REQUIRED_ENV = (
    "TELEGRAM_TOKEN",
    "ALLOWED_USERS",
    "ADMIN_USERS",
    "DATABASE_URL",
    "DB_PASS",
    "HERMES_TIMEZONE",
    "HERMES_GROUP_CHAT_MODE",
    "HERMES_BACKUP_RETENTION_DAYS",
    "HERMES_AUDIT_RETENTION_DAYS",
    "HERMES_OPERATION_RETENTION_DAYS",
    "GRAY_BOT_USERNAME",
    "RATE_LIMIT_MESSAGES",
    "RATE_LIMIT_WINDOW_SECONDS",
    "MAX_DOCUMENT_BYTES",
    "MAX_VOICE_BYTES",
    "MAX_PHOTO_BYTES",
)
INTEGER_ENV = {
    "HISTORY_LIMIT",
    "MEMORY_QUEUE_SIZE",
    "MEMORY_WORKERS",
    "RATE_LIMIT_MESSAGES",
    "RATE_LIMIT_WINDOW_SECONDS",
    "MAX_DOCUMENT_BYTES",
    "MAX_VOICE_BYTES",
    "MAX_PHOTO_BYTES",
    "DB_MIN_POOL_SIZE",
    "DB_MAX_POOL_SIZE",
    "SUMMARY_TRIGGER",
    "OLLAMA_NUM_CTX",
    "OLLAMA_LIVE_CONCURRENCY",
    "OLLAMA_BACKGROUND_CONCURRENCY",
    "MAX_MEMORY_FACTS",
    "MAX_MEMORY_CHARS",
    "MAX_CONTEXT_CHARS",
    "MAX_URL_CONTEXT_CHARS",
    "MAX_WIKI_CONTENT_CHARS",
    "MAX_INGEST_CHARS",
    "HERMES_SCHEDULER_INTERVAL_SECONDS",
    "HERMES_SCHEDULER_BATCH_SIZE",
    "HERMES_JOB_FAILURE_LIMIT",
    "HERMES_BACKUP_RETENTION_DAYS",
    "HERMES_AUDIT_RETENTION_DAYS",
    "HERMES_OPERATION_RETENTION_DAYS",
}


@dataclass(frozen=True)
class PreflightReport:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def load_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merged_env(env_file: str | Path | None = None) -> dict[str, str]:
    data = dict(os.environ)
    if env_file:
        data.update(load_env_file(env_file))
    return data


def collect_preflight_report(env: dict[str, str]) -> PreflightReport:
    errors: list[str] = []
    warnings: list[str] = []

    for key in REQUIRED_ENV:
        if not env.get(key):
            errors.append(f"Missing required env var: {key}")
        elif _looks_like_placeholder(env[key]):
            errors.append(f"{key} still contains a placeholder value.")

    model_provider = env.get("MODEL_PROVIDER", "deepseek").strip().lower()
    if model_provider not in {"ollama", "deepseek"}:
        errors.append("MODEL_PROVIDER must be one of: ollama, deepseek.")
    elif model_provider == "ollama":
        _require_provider_key(env, "OLLAMA_URL", errors)
        _require_provider_key(env, "OLLAMA_MODEL", errors)
    elif model_provider == "deepseek":
        _require_provider_key(env, "DEEPSEEK_API_KEY", errors)
        _require_provider_key(env, "DEEPSEEK_BASE_URL", errors)
        _require_provider_key(env, "DEEPSEEK_MODEL", errors)
        deepseek_url = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        parsed_deepseek = urlparse(deepseek_url)
        if parsed_deepseek.scheme not in {"http", "https"} or not parsed_deepseek.netloc:
            errors.append("DEEPSEEK_BASE_URL must be an http(s) URL.")

    embedding_provider = env.get("EMBEDDING_PROVIDER", "disabled").strip().lower()
    if embedding_provider not in {"ollama", "disabled"}:
        errors.append("EMBEDDING_PROVIDER must be one of: ollama, disabled.")
    elif embedding_provider == "ollama":
        _require_provider_key(env, "OLLAMA_URL", errors)
        _require_provider_key(env, "EMBED_MODEL", errors)

    db_url = env.get("DATABASE_URL", "")
    if db_url and not _looks_like_postgres_url(db_url):
        errors.append("DATABASE_URL must be a postgres/postgresql URL.")
    else:
        db_pass_for_url = env.get("DB_PASS", "")
        parsed_db = urlparse(db_url)
        url_password = unquote(parsed_db.password or "")
        if db_url and db_pass_for_url and url_password and url_password != db_pass_for_url:
            errors.append("DATABASE_URL password must match DB_PASS.")

    token = env.get("TELEGRAM_TOKEN", "")
    if token and not re.match(r"^\d+:[A-Za-z0-9_-]{20,}$", token):
        warnings.append("TELEGRAM_TOKEN does not look like a Telegram bot token.")

    db_pass = env.get("DB_PASS", "")
    if db_pass in {"changeme", "changeme_strong_password", "password", "postgres"} or _looks_like_placeholder(db_pass):
        errors.append("DB_PASS is still a default or weak placeholder.")
    elif db_pass and len(db_pass) < 16:
        warnings.append("DB_PASS is shorter than 16 characters.")

    allowed = env.get("ALLOWED_USERS", "")
    if allowed and not _valid_allowed_users(allowed):
        errors.append("ALLOWED_USERS must be comma-separated Telegram numeric IDs.")
    if not allowed:
        errors.append("ALLOWED_USERS must be set so Gray is not open to every Telegram user.")

    admins = env.get("ADMIN_USERS", "")
    if admins and not _valid_allowed_users(admins):
        errors.append("ADMIN_USERS must be comma-separated Telegram numeric IDs.")
    if not admins:
        errors.append("ADMIN_USERS must be set so Hermes admin commands are not ownerless.")
    elif allowed:
        allowed_ids = _parse_user_ids(allowed)
        for admin_id in _parse_user_ids(admins):
            if admin_id not in allowed_ids:
                errors.append("ADMIN_USERS must be a subset of ALLOWED_USERS.")
                break

    operators = env.get("OPERATOR_USERS", "")
    if operators and not _valid_allowed_users(operators):
        errors.append("OPERATOR_USERS must be comma-separated Telegram numeric IDs.")
    elif operators and allowed:
        allowed_ids = _parse_user_ids(allowed)
        for operator_id in _parse_user_ids(operators):
            if operator_id not in allowed_ids:
                errors.append("OPERATOR_USERS must be a subset of ALLOWED_USERS.")
                break

    group_mode = env.get("HERMES_GROUP_CHAT_MODE", "mention").strip().lower()
    if group_mode not in {"mention", "all", "always", "off", "never"}:
        errors.append("HERMES_GROUP_CHAT_MODE must be one of: mention, all, always, off, never.")

    timezone = env.get("HERMES_TIMEZONE", "")
    if timezone:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            errors.append("HERMES_TIMEZONE must be a valid IANA timezone, for example Asia/Singapore.")

    ollama_url = env.get("OLLAMA_URL", "")
    if ollama_url:
        parsed = urlparse(ollama_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append("OLLAMA_URL must be an http(s) URL.")
        elif parsed.hostname in {"localhost", "127.0.0.1"}:
            warnings.append(
                "OLLAMA_URL points at localhost. In Docker Compose deploys use "
                "http://host.docker.internal:11434 so the bot container can reach host Ollama."
            )

    for key in INTEGER_ENV:
        value = env.get(key)
        if value and not _positive_int(value):
            errors.append(f"{key} must be a positive integer.")

    db_min_pool = env.get("DB_MIN_POOL_SIZE")
    db_max_pool = env.get("DB_MAX_POOL_SIZE")
    if db_min_pool and db_max_pool and _positive_int(db_min_pool) and _positive_int(db_max_pool):
        if int(db_min_pool) > int(db_max_pool):
            errors.append("DB_MIN_POOL_SIZE must be less than or equal to DB_MAX_POOL_SIZE.")

    return PreflightReport(errors=errors, warnings=warnings)


def render_report(report: PreflightReport) -> str:
    lines = ["Gray/Hermes preflight"]
    if report.errors:
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in report.errors)
    if report.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    if report.ok:
        lines.append("Status: OK")
    else:
        lines.append("Status: FAILED")
    return "\n".join(lines)


def _looks_like_postgres_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"postgres", "postgresql"} and bool(parsed.hostname)


def _valid_allowed_users(value: str) -> bool:
    return all(part.strip().isdigit() for part in value.split(",") if part.strip())


def _parse_user_ids(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def _positive_int(value: str) -> bool:
    try:
        return int(value) >= 1
    except ValueError:
        return False


def _require_provider_key(env: dict[str, str], key: str, errors: list[str]) -> None:
    value = env.get(key, "")
    if not value:
        errors.append(f"Missing required env var: {key}")
    elif _looks_like_placeholder(value):
        errors.append(f"{key} still contains a placeholder value.")


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return any(marker in lowered for marker in ("replace_", "replace-with", "your_", "example_", "<"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Gray/Hermes deployment config.")
    parser.add_argument("--env-file", default=".env", help="Path to .env file.")
    args = parser.parse_args()
    report = collect_preflight_report(merged_env(args.env_file))
    print(render_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
