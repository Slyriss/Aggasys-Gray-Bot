import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from subprocess import CompletedProcess
from unittest.mock import call, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import docker_build_smoke


class DockerBuildSmokeTests(unittest.TestCase):
    def test_reports_unreachable_docker_engine(self):
        with patch.object(sys, "argv", ["docker_build_smoke.py"]), \
             patch.object(docker_build_smoke.subprocess, "run",
                          return_value=CompletedProcess(["docker"], 1, stderr="not running")), \
             redirect_stdout(StringIO()), \
             redirect_stderr(StringIO()) as stderr:
            result = docker_build_smoke.main()

        self.assertEqual(result, 1)
        self.assertIn("Docker engine is not reachable", stderr.getvalue())

    def test_builds_default_tag_after_docker_version_passes(self):
        version = CompletedProcess(["docker", "version"], 0)
        build = CompletedProcess(["docker", "build"], 0)

        with patch.object(sys, "argv", ["docker_build_smoke.py"]), \
             patch.object(docker_build_smoke.subprocess, "run",
                          side_effect=[version, build]) as run, \
             redirect_stdout(StringIO()) as stdout:
            result = docker_build_smoke.main()

        self.assertEqual(result, 0)
        self.assertIn("Docker build smoke passed: aggasys-gray-bot:smoke", stdout.getvalue())
        self.assertEqual(run.call_args_list[1], call(
            ["docker", "build", "-t", "aggasys-gray-bot:smoke", "-f", "bot/Dockerfile", "bot"],
            cwd=docker_build_smoke.ROOT,
        ))

    def test_build_supports_custom_tag_and_no_cache(self):
        version = CompletedProcess(["docker", "version"], 0)
        build = CompletedProcess(["docker", "build"], 0)

        with patch.object(sys, "argv", ["docker_build_smoke.py", "--tag", "gray:test", "--no-cache"]), \
             patch.object(docker_build_smoke.subprocess, "run",
                          side_effect=[version, build]) as run, \
             redirect_stdout(StringIO()):
            result = docker_build_smoke.main()

        self.assertEqual(result, 0)
        self.assertEqual(run.call_args_list[1], call(
            ["docker", "build", "-t", "gray:test", "-f", "bot/Dockerfile", "--no-cache", "bot"],
            cwd=docker_build_smoke.ROOT,
        ))


if __name__ == "__main__":
    unittest.main()
