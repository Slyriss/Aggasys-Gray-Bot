from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Gray/Hermes release readiness gates.")
    parser.add_argument("--include-heavy", action="store_true", help="Run heavyweight runtime import checks.")
    parser.add_argument("--include-docker", action="store_true", help="Run Docker image build smoke.")
    parser.add_argument("--skip-resolution", action="store_true", help="Skip pip dry-run dependency resolution.")
    args = parser.parse_args(argv)

    commands = [
        [sys.executable, "scripts/run_checks.py"],
    ]
    if not args.skip_resolution:
        commands.append([sys.executable, "scripts/check_requirements_resolution.py"])
    commands.append([sys.executable, "scripts/check_hostinger_readiness.py"])
    if args.include_heavy:
        commands.append([sys.executable, "scripts/runtime_import_smoke.py", "--include-heavy"])
    if args.include_docker:
        commands.append([sys.executable, "scripts/docker_build_smoke.py"])

    for command in commands:
        if _run(command) != 0:
            print("Release readiness failed.", file=sys.stderr)
            return 1

    print("Release readiness OK")
    if not args.include_docker:
        print("Docker build smoke skipped. Run with --include-docker when Docker is available.")
    return 0


def _run(command: list[str]) -> int:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
