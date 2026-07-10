import os
import sys
import unittest
from pathlib import Path


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.check_in_venv import _venv_python


class CheckInVenvTests(unittest.TestCase):
    def test_venv_python_path_matches_platform(self):
        venv_path = Path("workspace") / ".venv"

        python = _venv_python(venv_path)

        if os.name == "nt":
            self.assertEqual(python, venv_path / "Scripts" / "python.exe")
        else:
            self.assertEqual(python, venv_path / "bin" / "python")


if __name__ == "__main__":
    unittest.main()
