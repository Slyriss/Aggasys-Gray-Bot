from __future__ import annotations

import subprocess
import sys


CHECKS = [
    [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
    [sys.executable, "-m", "compileall", "-q", "bot", "tests", "scripts"],
    [sys.executable, "scripts/scan_secret_hygiene.py"],
    [sys.executable, "scripts/runtime_import_smoke.py"],
    [sys.executable, "scripts/verify_deployment_assets.py"],
    [sys.executable, "scripts/verify_runtime_assets.py"],
    [sys.executable, "scripts/verify_schema_assets.py"],
    [sys.executable, "scripts/verify_policy_registry.py"],
    [sys.executable, "scripts/verify_command_surface.py"],
]


def main() -> int:
    for command in CHECKS:
        print("+ " + " ".join(command))
        result = subprocess.run(command)
        if result.returncode != 0:
            return result.returncode
    print("All local checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
