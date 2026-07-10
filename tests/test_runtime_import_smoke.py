import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.runtime_import_smoke import CORE_RUNTIME_IMPORTS, HEAVY_RUNTIME_IMPORTS, RUNTIME_IMPORTS, main as runtime_import_smoke


class RuntimeImportSmokeTests(unittest.TestCase):
    def test_runtime_import_list_covers_known_requirements(self):
        self.assertEqual(RUNTIME_IMPORTS["python-telegram-bot"], "telegram")
        self.assertEqual(RUNTIME_IMPORTS["duckduckgo-search"], "duckduckgo_search")
        self.assertEqual(RUNTIME_IMPORTS["faster-whisper"], "faster_whisper")
        self.assertEqual(RUNTIME_IMPORTS["tzdata"], "tzdata")
        self.assertEqual(HEAVY_RUNTIME_IMPORTS["faster-whisper"], "faster_whisper")
        self.assertNotIn("faster-whisper", CORE_RUNTIME_IMPORTS)

    def test_runtime_import_smoke_passes_in_current_environment(self):
        self.assertEqual(runtime_import_smoke([]), 0)


if __name__ == "__main__":
    unittest.main()
