import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BackupRestoreAssetTests(unittest.TestCase):
    def test_backup_waits_for_postgres_and_validates_dump_output(self):
        backup = (ROOT / "scripts" / "backup_hermes_data.sh").read_text(encoding="utf-8")

        self.assertIn("pg_isready -U aggasys -d aggasys", backup)
        self.assertIn("psql -v ON_ERROR_STOP=1 -U aggasys -d aggasys -tAc", backup)
        self.assertIn("PostgreSQL database dump", backup)
        self.assertIn("[ ! -s \"$OUT\" ]", backup)

    def test_restore_requires_explicit_confirmation_and_hermes_inserts(self):
        restore = (ROOT / "scripts" / "restore_hermes_data.sh").read_text(encoding="utf-8")

        self.assertIn('CONFIRM=${2:-}', restore)
        self.assertIn('"$CONFIRM" != "--yes"', restore)
        self.assertIn("Hermes operational table inserts", restore)
        self.assertIn("TRUNCATE hermes_audit_log", restore)
        self.assertIn("-v ON_ERROR_STOP=1", restore)


if __name__ == "__main__":
    unittest.main()
