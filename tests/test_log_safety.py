import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOT_DIR = os.path.join(ROOT, "bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from log_safety import exception_type, safe_url_host, text_size


class LogSafetyTests(unittest.TestCase):
    def test_safe_url_host_keeps_host_only(self):
        host = safe_url_host("https://user:secret@example.com/path?token=sk-secret")

        self.assertEqual(host, "example.com")
        self.assertNotIn("secret", host)
        self.assertNotIn("token", host)

    def test_exception_type_omits_exception_message(self):
        exc = RuntimeError("sk-secret-value")

        self.assertEqual(exception_type(exc), "RuntimeError")
        self.assertNotIn("sk-secret-value", exception_type(exc))

    def test_text_size_reports_size_without_returning_text(self):
        value = "sensitive-result"

        self.assertEqual(text_size(value), len(value))


if __name__ == "__main__":
    unittest.main()
