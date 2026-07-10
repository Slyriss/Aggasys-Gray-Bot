import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DockerRuntimeAssetTests(unittest.TestCase):
    def test_dockerfile_installs_runtime_system_dependencies(self):
        dockerfile = (ROOT / "bot" / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("ffmpeg", dockerfile)
        self.assertIn("libgomp1", dockerfile)
        self.assertIn("ca-certificates", dockerfile)
        self.assertIn("rm -rf /var/lib/apt/lists/*", dockerfile)

    def test_dockerignore_keeps_secrets_and_cache_out_of_image_context(self):
        dockerignore = (ROOT / "bot" / ".dockerignore").read_text(encoding="utf-8")

        self.assertIn(".env", dockerignore)
        self.assertIn(".env.*", dockerignore)
        self.assertIn("__pycache__/", dockerignore)
        self.assertIn("*.pyc", dockerignore)


if __name__ == "__main__":
    unittest.main()
