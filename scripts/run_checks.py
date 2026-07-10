from __future__ import annotations

import argparse
import subprocess
import sys


CHECKS = [
    [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
    [sys.executable, "-m", "compileall", "-q", "bot", "tests", "scripts"],
    [sys.executable, "scripts/scan_secret_hygiene.py"],
    [sys.executable, "scripts/runtime_import_smoke.py"],
    [sys.executable, "scripts/verify_deploy_status.py"],
    [sys.executable, "scripts/verify_deployment_assets.py"],
    [sys.executable, "scripts/verify_runtime_assets.py"],
    [sys.executable, "scripts/verify_schema_assets.py"],
    [sys.executable, "scripts/verify_policy_registry.py"],
    [sys.executable, "scripts/verify_command_surface.py"],
]
DEPLOY_STATUS_CHECK = [sys.executable, "scripts/verify_deploy_status.py"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Gray/Hermes local verification gates.")
    parser.add_argument(
        "--skip-deploy-status",
        action="store_true",
        help="Skip DEPLOY_STATUS.md verification while that artifact is being generated.",
    )
    args = parser.parse_args(argv)

    for command in CHECKS:
        if args.skip_deploy_status and command == DEPLOY_STATUS_CHECK:
            continue
        print("+ " + " ".join(command))
        result = subprocess.run(command)
        if result.returncode != 0:
            return result.returncode
    print("All local checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
