import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import release_readiness


class ReleaseReadinessTests(unittest.TestCase):
    def test_default_release_readiness_runs_safe_gates_without_docker(self):
        seen = []

        def fake_run(command):
            seen.append(command)
            return 0

        with patch.object(release_readiness, "_run", side_effect=fake_run):
            result = release_readiness.main([])

        self.assertEqual(result, 0)
        flattened = [" ".join(command) for command in seen]
        self.assertTrue(any("scripts/run_checks.py" in item for item in flattened))
        self.assertTrue(any("scripts/check_requirements_resolution.py" in item for item in flattened))
        self.assertTrue(any("scripts/check_hostinger_readiness.py" in item for item in flattened))
        self.assertFalse(any("scripts/docker_build_smoke.py" in item for item in flattened))

    def test_release_readiness_can_include_heavy_and_docker_gates(self):
        seen = []

        def fake_run(command):
            seen.append(command)
            return 0

        with patch.object(release_readiness, "_run", side_effect=fake_run):
            result = release_readiness.main(["--include-heavy", "--include-docker"])

        self.assertEqual(result, 0)
        flattened = [" ".join(command) for command in seen]
        self.assertTrue(any("scripts/runtime_import_smoke.py --include-heavy" in item for item in flattened))
        self.assertTrue(any("scripts/docker_build_smoke.py" in item for item in flattened))


if __name__ == "__main__":
    unittest.main()
