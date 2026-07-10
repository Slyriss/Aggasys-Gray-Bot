import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DeployRollbackAssetTests(unittest.TestCase):
    def test_deploy_helper_tags_previous_image_and_rolls_back_on_failed_health(self):
        script = (ROOT / "scripts" / "deploy_bot_with_rollback.sh").read_text(encoding="utf-8")

        self.assertIn("docker compose images -q bot", script)
        self.assertIn("docker tag \"$previous_image\" \"$ROLLBACK_IMAGE\"", script)
        self.assertIn("docker compose up -d --build bot", script)
        self.assertIn("scripts/check_post_deploy_health.sh --since", script)
        self.assertIn("docker tag \"$ROLLBACK_IMAGE\" aggasys-bot-bot:latest", script)
        self.assertIn("docker compose up -d --no-build bot", script)

    def test_health_checker_can_scope_logs_to_current_startup_window(self):
        script = (ROOT / "scripts" / "check_post_deploy_health.sh").read_text(encoding="utf-8")

        self.assertIn("--since", script)
        self.assertIn("LOG_SINCE_ARGS", script)
        self.assertIn("docker compose logs \"${LOG_SINCE_ARGS[@]}\" --tail=160 bot", script)


if __name__ == "__main__":
    unittest.main()
