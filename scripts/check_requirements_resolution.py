from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "bot" / "requirements.txt"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run resolve bot runtime requirements with pip.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use.")
    args = parser.parse_args()

    if not REQUIREMENTS.exists():
        print("bot/requirements.txt is missing.", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile(prefix="gray-pip-report-", suffix=".json", delete=False) as report:
        report_path = Path(report.name)

    command = _pip_dry_run_command(args.python, report_path)
    print("+ " + " ".join(str(part) for part in command))
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print("Requirements resolution failed.", file=sys.stderr)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        _cleanup(report_path)
        return result.returncode

    try:
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Could not read pip dry-run report: {exc}", file=sys.stderr)
        _cleanup(report_path)
        return 1
    finally:
        _cleanup(report_path)

    planned = report_data.get("install", [])
    print(f"Requirements resolution OK: {len(planned)} package(s) in dry-run plan")
    return 0


def _pip_dry_run_command(python: str, report_path: Path) -> list[str]:
    return [
        python,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--ignore-installed",
        "--report",
        str(report_path),
        "-r",
        str(REQUIREMENTS),
    ]


def _cleanup(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
