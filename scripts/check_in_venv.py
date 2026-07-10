from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = ROOT / ".venv"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/use a local venv and run Gray checks inside it.")
    parser.add_argument("--venv", default=str(DEFAULT_VENV), help="Virtualenv directory.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the venv first.")
    parser.add_argument("--include-heavy", action="store_true", help="Also run heavyweight runtime imports.")
    args = parser.parse_args()

    venv_path = Path(args.venv)
    if not venv_path.is_absolute():
        venv_path = ROOT / venv_path

    if args.recreate and venv_path.exists():
        if venv_path == ROOT or ROOT not in venv_path.parents:
            print(f"Refusing to delete unsafe venv path: {venv_path}", file=sys.stderr)
            return 1
        shutil.rmtree(venv_path)

    if not venv_path.exists():
        print(f"+ create venv {venv_path}")
        venv.EnvBuilder(with_pip=True, clear=False).create(venv_path)

    python = _venv_python(venv_path)
    if not python.exists():
        print(f"Could not find venv Python at {python}", file=sys.stderr)
        return 1

    commands = [
        [str(python), "-m", "pip", "install", "-r", "bot/requirements.txt"],
        [str(python), "scripts/check_requirements_resolution.py", "--python", str(python)],
        [str(python), "scripts/run_checks.py"],
    ]
    if args.include_heavy:
        commands.append([str(python), "scripts/runtime_import_smoke.py", "--include-heavy"])

    for command in commands:
        print("+ " + " ".join(command))
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            return result.returncode

    print(f"Venv checks passed: {venv_path}")
    return 0


def _venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


if __name__ == "__main__":
    raise SystemExit(main())
