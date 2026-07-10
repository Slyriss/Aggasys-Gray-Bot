from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAG = "aggasys-gray-bot:smoke"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Gray bot Docker image as a deploy smoke test.")
    parser.add_argument("--tag", default=DEFAULT_TAG, help="Docker image tag to build.")
    parser.add_argument("--no-cache", action="store_true", help="Build without Docker cache.")
    args = parser.parse_args()

    version = subprocess.run(
        ["docker", "version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if version.returncode != 0:
        print("Docker engine is not reachable. Start Docker, then rerun this build smoke.", file=sys.stderr)
        if version.stderr:
            print(version.stderr, file=sys.stderr)
        return version.returncode

    command = [
        "docker",
        "build",
        "-t",
        args.tag,
        "-f",
        "bot/Dockerfile",
    ]
    if args.no_cache:
        command.append("--no-cache")
    command.append("bot")

    print("+ " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    print(f"Docker build smoke passed: {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
