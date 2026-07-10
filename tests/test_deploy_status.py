import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.verify_deploy_status import verify_status


class DeployStatusTests(unittest.TestCase):
    def test_accepts_redacted_healthy_status(self):
        findings = self._verify(
            """
# VM Deploy Status

bot-1 | INFO:httpx:POST https://api.telegram.org/bot***/getUpdates
MODEL_PROVIDER=deepseek
EMBEDDING_PROVIDER=disabled
Application started
Post-deploy health check OK
"""
        )

        self.assertEqual(findings, [])

    def test_rejects_unredacted_telegram_token(self):
        findings = self._verify(
            """
MODEL_PROVIDER=deepseek
EMBEDDING_PROVIDER=disabled
Application started
Post-deploy health check OK
https://api.telegram.org/bot123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi/getMe
"""
        )

        self.assertTrue(any("Telegram bot token" in finding for finding in findings))

    def test_rejects_runtime_auth_failure(self):
        findings = self._verify(
            """
MODEL_PROVIDER=deepseek
EMBEDDING_PROVIDER=disabled
Application started
Post-deploy health check OK
Hermes scheduler tick failed: password authentication failed for user "aggasys"
"""
        )

        self.assertTrue(any("password authentication failed" in finding for finding in findings))
        self.assertTrue(any("Hermes scheduler tick failed" in finding for finding in findings))

    def test_rejects_missing_health_markers(self):
        findings = self._verify("# VM Deploy Status\n")

        self.assertTrue(any("Post-deploy health check OK" in finding for finding in findings))

    def _verify(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DEPLOY_STATUS.md"
            path.write_text(text, encoding="utf-8")
            return verify_status(path)


if __name__ == "__main__":
    unittest.main()
