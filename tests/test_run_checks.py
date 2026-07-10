import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import run_checks


class RunChecksTests(unittest.TestCase):
    def test_skip_deploy_status_omits_only_status_check(self):
        seen = []

        def fake_run(command):
            seen.append(command)

            class Result:
                returncode = 0

            return Result()

        with patch.object(run_checks.subprocess, "run", side_effect=fake_run):
            result = run_checks.main(["--skip-deploy-status"])

        self.assertEqual(result, 0)
        self.assertNotIn(run_checks.DEPLOY_STATUS_CHECK, seen)
        self.assertTrue(any("scripts/scan_secret_hygiene.py" in command for command in seen))


if __name__ == "__main__":
    unittest.main()
