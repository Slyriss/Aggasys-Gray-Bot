import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.verify_command_surface import main as verify_command_surface


class CommandSurfaceTests(unittest.TestCase):
    def test_registered_commands_help_and_smoke_docs_stay_aligned(self):
        self.assertEqual(verify_command_surface(), 0)


if __name__ == "__main__":
    unittest.main()
