import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot.preflight import collect_preflight_report, load_env_file
from scripts.create_env_from_example import _render_env


def _database_url(password: str) -> str:
    return "postgresql://aggasys:" + password + "@postgres:5432/aggasys"


class CreateEnvFromExampleTests(unittest.TestCase):
    def test_render_env_sets_matching_encoded_database_password(self):
        template = "\n".join([
            "DB_PASS=replace_with_a_long_random_password",
            "DATABASE_URL=postgresql://aggasys:replace_with_a_long_random_password@postgres:5432/aggasys",
            "TELEGRAM_TOKEN=123456789:replace_with_bot_token",
        ])

        rendered = _render_env(template, "very long/password")

        self.assertIn("DB_PASS=very long/password", rendered)
        self.assertIn("DATABASE_URL=" + _database_url("very%20long%2Fpassword"), rendered)

    def test_rendered_env_still_requires_operator_secrets(self):
        rendered = _render_env(
            "TELEGRAM_TOKEN=123456789:replace_with_bot_token\n"
            "ALLOWED_USERS=123456789\n"
            "DB_PASS=replace_with_a_long_random_password\n"
            "DATABASE_URL=postgresql://aggasys:replace_with_a_long_random_password@postgres:5432/aggasys\n"
            "OLLAMA_URL=http://host.docker.internal:11434\n"
            "OLLAMA_MODEL=qwen2.5:3b\n"
            "EMBED_MODEL=nomic-embed-text\n"
            "HERMES_TIMEZONE=Asia/Singapore\n"
            "HERMES_GROUP_CHAT_MODE=mention\n"
            "GRAY_BOT_USERNAME=GrayBot\n",
            "verylongpassword",
        )
        env = {}
        for line in rendered.splitlines():
            if line and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value

        report = collect_preflight_report(env)

        self.assertFalse(report.ok)
        self.assertIn("TELEGRAM_TOKEN still contains a placeholder value.", report.errors)


if __name__ == "__main__":
    unittest.main()
