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
        self.assertIn("HERMES_BACKUP_RETENTION_DAYS", backup)
        self.assertIn("find \"$BACKUP_DIR\" -maxdepth 1 -type f -name 'hermes-*.sql'", backup)
        self.assertIn("-mtime +\"$BACKUP_RETENTION_DAYS\"", backup)

    def test_restore_requires_explicit_confirmation_and_hermes_inserts(self):
        restore = (ROOT / "scripts" / "restore_hermes_data.sh").read_text(encoding="utf-8")

        self.assertIn('CONFIRM=${2:-}', restore)
        self.assertIn('"$CONFIRM" != "--yes"', restore)
        self.assertIn("Hermes operational table inserts", restore)
        self.assertIn("TRUNCATE hermes_audit_log", restore)
        self.assertIn("-v ON_ERROR_STOP=1", restore)

    def test_sync_postgres_password_reads_env_and_hides_secret(self):
        sync = (ROOT / "scripts" / "sync_postgres_password.sh").read_text(encoding="utf-8")

        self.assertIn("DB_PASS=", sync)
        self.assertIn("ALTER USER aggasys WITH PASSWORD", sync)
        self.assertIn(">/dev/null", sync)

    def test_retention_prune_script_is_dry_run_by_default(self):
        script = (ROOT / "scripts" / "prune_hermes_data.py").read_text(encoding="utf-8")

        self.assertIn("Hermes retention dry run", script)
        self.assertIn("--yes", script)
        self.assertIn("prune_hermes_retention", script)
        self.assertIn("get_hermes_retention_counts", script)
        self.assertIn("HERMES_AUDIT_RETENTION_DAYS", script)
        self.assertIn("HERMES_OPERATION_RETENTION_DAYS", script)

    def test_db_retention_only_prunes_resolved_inactive_operational_rows(self):
        db = (ROOT / "bot" / "db.py").read_text(encoding="utf-8")

        self.assertIn("get_hermes_retention_counts", db)
        self.assertIn("prune_hermes_retention", db)
        self.assertIn("status IN ('approved', 'denied', 'expired')", db)
        self.assertIn("status IN ('removed', 'paused')", db)
        self.assertIn("status = 'closed'", db)
        self.assertIn("completed_at < NOW()", db)


if __name__ == "__main__":
    unittest.main()
