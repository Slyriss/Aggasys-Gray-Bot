import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from preflight import collect_preflight_report, render_report
from scripts.verify_deployment_assets import main as verify_deployment_assets


def _database_url(password: str) -> str:
    return "postgresql://aggasys:" + password + "@postgres:5432/aggasys"


VALID_ENV = {
    "TELEGRAM_TOKEN": "123456789:abcdefghijklmnopqrstuvwxyz",
    "DATABASE_URL": _database_url("verylongpassword"),
    "DB_PASS": "verylongpassword",
    "ALLOWED_USERS": "123456789,987654321",
    "ADMIN_USERS": "123456789",
    "OPERATOR_USERS": "987654321",
    "MODEL_PROVIDER": "deepseek",
    "DEEPSEEK_API_KEY": "sk-" + "x" * 32,
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DEEPSEEK_MODEL": "deepseek-v4-flash",
    "EMBEDDING_PROVIDER": "disabled",
    "HERMES_TIMEZONE": "Asia/Singapore",
    "HERMES_GROUP_CHAT_MODE": "mention",
    "GRAY_BOT_USERNAME": "GrayBot",
    "RATE_LIMIT_MESSAGES": "30",
    "RATE_LIMIT_WINDOW_SECONDS": "60",
    "MAX_DOCUMENT_BYTES": "5242880",
    "MAX_VOICE_BYTES": "10485760",
    "MAX_PHOTO_BYTES": "5242880",
    "HERMES_BACKUP_RETENTION_DAYS": "30",
    "HERMES_AUDIT_RETENTION_DAYS": "180",
    "HERMES_OPERATION_RETENTION_DAYS": "365",
}


class PreflightTests(unittest.TestCase):
    def test_valid_env_passes(self):
        report = collect_preflight_report(dict(VALID_ENV))

        self.assertTrue(report.ok)
        self.assertEqual(report.errors, [])

    def test_missing_required_env_fails(self):
        env = dict(VALID_ENV)
        env.pop("TELEGRAM_TOKEN")

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("Missing required env var: TELEGRAM_TOKEN", report.errors)

    def test_weak_db_password_fails(self):
        env = dict(VALID_ENV)
        env["DB_PASS"] = "changeme_strong_password"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertTrue(any("DB_PASS" in error for error in report.errors))

    def test_database_url_password_must_match_db_pass(self):
        env = dict(VALID_ENV)
        env["DB_PASS"] = "verylongpassword"
        env["DATABASE_URL"] = _database_url("differentpassword")

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("DATABASE_URL password must match DB_PASS.", report.errors)

    def test_database_url_encoded_password_can_match_db_pass(self):
        env = dict(VALID_ENV)
        env["DB_PASS"] = "very long/password"
        env["DATABASE_URL"] = _database_url("very%20long%2Fpassword")

        report = collect_preflight_report(env)

        self.assertTrue(report.ok)

    def test_bad_allowed_users_fails(self):
        env = dict(VALID_ENV)
        env["ALLOWED_USERS"] = "123,abc"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("ALLOWED_USERS must be comma-separated Telegram numeric IDs.", report.errors)

    def test_admin_users_are_required(self):
        env = dict(VALID_ENV)
        env["ADMIN_USERS"] = ""

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("ADMIN_USERS must be set so Hermes admin commands are not ownerless.", report.errors)

    def test_role_users_must_be_allowed(self):
        env = dict(VALID_ENV)
        env["ADMIN_USERS"] = "555555555"
        env["OPERATOR_USERS"] = "666666666"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("ADMIN_USERS must be a subset of ALLOWED_USERS.", report.errors)
        self.assertIn("OPERATOR_USERS must be a subset of ALLOWED_USERS.", report.errors)

    def test_role_users_must_be_numeric(self):
        env = dict(VALID_ENV)
        env["ADMIN_USERS"] = "alice"
        env["OPERATOR_USERS"] = "123,bob"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("ADMIN_USERS must be comma-separated Telegram numeric IDs.", report.errors)
        self.assertIn("OPERATOR_USERS must be comma-separated Telegram numeric IDs.", report.errors)

    def test_empty_allowed_users_fails(self):
        env = dict(VALID_ENV)
        env["ALLOWED_USERS"] = ""

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("ALLOWED_USERS must be set so Gray is not open to every Telegram user.", report.errors)

    def test_bad_group_mode_fails(self):
        env = dict(VALID_ENV)
        env["HERMES_GROUP_CHAT_MODE"] = "loud"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("HERMES_GROUP_CHAT_MODE must be one of: mention, all, always, off, never.", report.errors)

    def test_bad_rate_limit_values_fail(self):
        env = dict(VALID_ENV)
        env["RATE_LIMIT_MESSAGES"] = "0"
        env["RATE_LIMIT_WINDOW_SECONDS"] = "soon"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("RATE_LIMIT_MESSAGES must be a positive integer.", report.errors)
        self.assertIn("RATE_LIMIT_WINDOW_SECONDS must be a positive integer.", report.errors)

    def test_bad_backup_retention_fails(self):
        env = dict(VALID_ENV)
        env["HERMES_BACKUP_RETENTION_DAYS"] = "never"
        env["HERMES_AUDIT_RETENTION_DAYS"] = "0"
        env["HERMES_OPERATION_RETENTION_DAYS"] = "old"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("HERMES_BACKUP_RETENTION_DAYS must be a positive integer.", report.errors)
        self.assertIn("HERMES_AUDIT_RETENTION_DAYS must be a positive integer.", report.errors)
        self.assertIn("HERMES_OPERATION_RETENTION_DAYS must be a positive integer.", report.errors)

    def test_bad_upload_limit_values_fail(self):
        env = dict(VALID_ENV)
        env["MAX_DOCUMENT_BYTES"] = "0"
        env["MAX_VOICE_BYTES"] = "-1"
        env["MAX_PHOTO_BYTES"] = "big"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("MAX_DOCUMENT_BYTES must be a positive integer.", report.errors)
        self.assertIn("MAX_VOICE_BYTES must be a positive integer.", report.errors)
        self.assertIn("MAX_PHOTO_BYTES must be a positive integer.", report.errors)

    def test_bad_timezone_fails(self):
        env = dict(VALID_ENV)
        env["HERMES_TIMEZONE"] = "Singapore/DefinitelyNotReal"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("HERMES_TIMEZONE must be a valid IANA timezone, for example Asia/Singapore.", report.errors)

    def test_missing_deepseek_model_name_fails(self):
        env = dict(VALID_ENV)
        env.pop("DEEPSEEK_MODEL")

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("Missing required env var: DEEPSEEK_MODEL", report.errors)

    def test_ollama_provider_requires_ollama_config(self):
        env = dict(VALID_ENV)
        env["MODEL_PROVIDER"] = "ollama"
        env.pop("OLLAMA_MODEL", None)
        env.pop("OLLAMA_URL", None)

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("Missing required env var: OLLAMA_MODEL", report.errors)
        self.assertIn("Missing required env var: OLLAMA_URL", report.errors)

    def test_localhost_ollama_warns_for_docker_deploys(self):
        env = dict(VALID_ENV)
        env["MODEL_PROVIDER"] = "ollama"
        env["OLLAMA_MODEL"] = "qwen2.5:3b"
        env["OLLAMA_URL"] = "http://localhost:11434"

        report = collect_preflight_report(env)

        self.assertTrue(report.ok)
        self.assertTrue(any("host.docker.internal" in warning for warning in report.warnings))

    def test_placeholder_values_fail(self):
        env = dict(VALID_ENV)
        env["TELEGRAM_TOKEN"] = "123456789:replace_with_bot_token"

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("TELEGRAM_TOKEN still contains a placeholder value.", report.errors)

    def test_render_report_includes_status(self):
        report = collect_preflight_report(dict(VALID_ENV))
        rendered = render_report(report)

        self.assertIn("Gray/Hermes preflight", rendered)
        self.assertIn("Status: OK", rendered)

    def test_deployment_assets_verify(self):
        self.assertEqual(verify_deployment_assets(), 0)


if __name__ == "__main__":
    unittest.main()
