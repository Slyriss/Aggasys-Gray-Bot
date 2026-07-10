import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.scan_secret_hygiene import scan_repository


def _fake_telegram_token() -> str:
    return "123456789:" + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


def _database_url(password: str) -> str:
    return "postgresql://aggasys:" + password + "@postgres:5432/aggasys"


class SecretHygieneTests(unittest.TestCase):
    def test_allows_documented_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text(
                "TELEGRAM_TOKEN=123456789:replace_with_bot_token\n"
                "DB_PASS=replace_with_a_long_random_password\n"
                "DATABASE_URL=postgresql://aggasys:replace_with_a_long_random_password@postgres:5432/aggasys\n",
                encoding="utf-8",
            )

            findings = scan_repository(root)

            self.assertEqual(findings, [])

    def test_rejects_real_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TELEGRAM_TOKEN=123456789:replace_with_bot_token\n", encoding="utf-8")

            findings = scan_repository(root)

            self.assertTrue(any("Real .env file" in finding.message for finding in findings))

    def test_allows_env_file_only_when_deploy_override_is_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TELEGRAM_TOKEN=123456789:replace_with_bot_token\n", encoding="utf-8")

            with patch.dict(os.environ, {"ALLOW_WORKSPACE_ENV": "1"}):
                findings = scan_repository(root)

            self.assertFalse(any("Real .env file" in finding.message for finding in findings))

    def test_rejects_real_telegram_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.md").write_text(
                f"token {_fake_telegram_token()}\n",
                encoding="utf-8",
            )

            findings = scan_repository(root)

            self.assertTrue(any("Telegram bot token" in finding.message for finding in findings))

    def test_rejects_real_database_password_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "deploy.env").write_text(
                "DATABASE_URL=" + _database_url("super-secret-password") + "\n",
                encoding="utf-8",
            )

            findings = scan_repository(root)

            self.assertTrue(any("DATABASE_URL" in finding.message for finding in findings))
            self.assertTrue(any("Database URL" in finding.message for finding in findings))

    def test_skips_backups_and_binary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backups = root / "backups"
            backups.mkdir()
            (backups / "hermes.sql").write_text(
                f"TELEGRAM_TOKEN={_fake_telegram_token()}\n",
                encoding="utf-8",
            )
            (root / "image.png").write_bytes(_fake_telegram_token().encode("ascii"))

            findings = scan_repository(root)

            self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
