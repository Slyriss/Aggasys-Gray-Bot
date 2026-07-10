from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    checks = [
        [sys.executable, "scripts/run_checks.py"],
    ]
    for command in checks:
        result = _run(command)
        if result != 0:
            return result

    compose_result = _validate_compose_with_example_env()
    if compose_result != 0:
        return compose_result

    print("Hostinger readiness checks passed")
    print("Next gate: create a real .env and run bot/preflight.py against it on the VPS.")
    return 0


def _run(command: list[str]) -> int:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=ROOT).returncode


def _validate_compose_with_example_env() -> int:
    env_path = ROOT / ".env"
    example_path = ROOT / ".env.example"
    if env_path.exists():
        print("Refusing to overwrite existing .env during readiness check.", file=sys.stderr)
        return 1
    if not example_path.exists():
        print(".env.example is missing.", file=sys.stderr)
        return 1
    shutil.copyfile(example_path, env_path)
    try:
        print("+ docker compose config")
        result = subprocess.run(
            ["docker", "compose", "config"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
        return result.returncode
    finally:
        try:
            env_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
