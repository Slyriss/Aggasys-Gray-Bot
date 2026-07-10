import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import check_hostinger_readiness


class HostingerReadinessTests(unittest.TestCase):
    def test_refuses_to_overwrite_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("real=true", encoding="utf-8")
            (root / ".env.example").write_text("example=true", encoding="utf-8")

            with patch.object(check_hostinger_readiness, "ROOT", root), \
                 redirect_stderr(StringIO()):
                result = check_hostinger_readiness._validate_compose_with_example_env()

            self.assertEqual(result, 1)
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), "real=true")

    def test_removes_temporary_env_after_compose_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text("example=true", encoding="utf-8")

            with patch.object(check_hostinger_readiness, "ROOT", root), \
                 patch.object(check_hostinger_readiness.subprocess, "run",
                              return_value=CompletedProcess(["docker"], 0)) as run, \
                 redirect_stdout(StringIO()):
                result = check_hostinger_readiness._validate_compose_with_example_env()

            self.assertEqual(result, 0)
            self.assertFalse((root / ".env").exists())
            run.assert_called_once()

    def test_removes_temporary_env_after_compose_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text("example=true", encoding="utf-8")

            with patch.object(check_hostinger_readiness, "ROOT", root), \
                 patch.object(check_hostinger_readiness.subprocess, "run",
                              return_value=CompletedProcess(["docker"], 9, stderr="bad compose")), \
                 redirect_stdout(StringIO()), \
                 redirect_stderr(StringIO()):
                result = check_hostinger_readiness._validate_compose_with_example_env()

            self.assertEqual(result, 9)
            self.assertFalse((root / ".env").exists())


if __name__ == "__main__":
    unittest.main()
