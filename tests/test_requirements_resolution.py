import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.check_requirements_resolution import REQUIREMENTS, _pip_dry_run_command


class RequirementsResolutionTests(unittest.TestCase):
    def test_pip_dry_run_command_uses_isolated_resolution_flags(self):
        report_path = Path(tempfile.gettempdir()) / "gray-report.json"

        command = _pip_dry_run_command("python", report_path)

        self.assertIn("--dry-run", command)
        self.assertIn("--ignore-installed", command)
        self.assertIn("--report", command)
        self.assertIn(str(REQUIREMENTS), command)


if __name__ == "__main__":
    unittest.main()
