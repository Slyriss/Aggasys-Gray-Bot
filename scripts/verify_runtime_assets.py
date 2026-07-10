from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_REQUIREMENTS = {
    "python-telegram-bot",
    "asyncpg",
    "pgvector",
    "python-dotenv",
    "duckduckgo-search",
    "pytz",
    "tzdata",
    "httpx",
    "faster-whisper",
    "pdfplumber",
}

DOCKERFILE_MARKERS = [
    "FROM python:3.11-slim",
    "WORKDIR /app",
    "ca-certificates",
    "ffmpeg",
    "libgomp1",
    "COPY requirements.txt .",
    "pip install --no-cache-dir -r requirements.txt",
    'CMD ["python", "main.py"]',
]

COMPOSE_MARKERS = [
    "build: ./bot",
    "env_file: .env",
    "depends_on:",
    "condition: service_healthy",
    "postgres",
    "redis",
    "pg_isready -U aggasys -d aggasys",
    "redis-cli",
    "ping",
    "host.docker.internal:host-gateway",
]


def main() -> int:
    errors: list[str] = []

    requirements_path = ROOT / "bot" / "requirements.txt"
    dockerfile_path = ROOT / "bot" / "Dockerfile"
    compose_path = ROOT / "docker-compose.yml"
    backup_script_path = ROOT / "scripts" / "backup_hermes_data.sh"
    restore_script_path = ROOT / "scripts" / "restore_hermes_data.sh"
    build_smoke_path = ROOT / "scripts" / "docker_build_smoke.py"
    requirements_resolution_path = ROOT / "scripts" / "check_requirements_resolution.py"
    venv_check_path = ROOT / "scripts" / "check_in_venv.py"
    release_readiness_path = ROOT / "scripts" / "release_readiness.py"
    import_smoke_path = ROOT / "scripts" / "runtime_import_smoke.py"
    vps_prereqs_path = ROOT / "scripts" / "check_vps_prereqs.sh"
    post_deploy_path = ROOT / "scripts" / "check_post_deploy_health.sh"

    requirements = _read(requirements_path)
    installed = _requirement_names(requirements)
    for package in sorted(REQUIRED_REQUIREMENTS):
        if package not in installed:
            errors.append(f"bot/requirements.txt missing runtime package: {package}")
    if "httpx==0.25.2" not in requirements:
        errors.append("bot/requirements.txt must keep httpx==0.25.2 for python-telegram-bot 20.7 compatibility.")
    if "tzdata==" not in requirements:
        errors.append("bot/requirements.txt must include tzdata for ZoneInfo support in slim images and Windows venvs.")

    dockerfile = _read(dockerfile_path)
    for marker in DOCKERFILE_MARKERS:
        if marker not in dockerfile:
            errors.append(f"bot/Dockerfile missing marker: {marker}")

    compose = _read(compose_path)
    for marker in COMPOSE_MARKERS:
        if marker not in compose:
            errors.append(f"docker-compose.yml missing runtime marker: {marker}")

    dockerignore = _read(ROOT / "bot" / ".dockerignore")
    for marker in ("__pycache__/", "*.pyc", ".env"):
        if marker not in dockerignore:
            errors.append(f"bot/.dockerignore missing marker: {marker}")

    backup_script = _read(backup_script_path)
    for marker in ("pg_dump", "--data-only", "hermes_jobs", "standup_sessions", "pg_isready", "ON_ERROR_STOP=1", "PostgreSQL database dump"):
        if marker not in backup_script:
            errors.append(f"scripts/backup_hermes_data.sh missing marker: {marker}")

    restore_script = _read(restore_script_path)
    for marker in ("--yes", "TRUNCATE hermes_audit_log", "ON_ERROR_STOP=1", "standup_sessions", "pg_isready", "Hermes operational table inserts"):
        if marker not in restore_script:
            errors.append(f"scripts/restore_hermes_data.sh missing marker: {marker}")

    build_smoke = _read(build_smoke_path)
    for marker in ("docker", "build", "-f", "bot/Dockerfile"):
        if marker not in build_smoke:
            errors.append(f"scripts/docker_build_smoke.py missing marker: {marker}")

    requirements_resolution = _read(requirements_resolution_path)
    for marker in ("--dry-run", "--ignore-installed", "--report", "Requirements resolution OK"):
        if marker not in requirements_resolution:
            errors.append(f"scripts/check_requirements_resolution.py missing marker: {marker}")

    venv_check = _read(venv_check_path)
    for marker in ("venv.EnvBuilder", "pip", "bot/requirements.txt", "scripts/run_checks.py"):
        if marker not in venv_check:
            errors.append(f"scripts/check_in_venv.py missing marker: {marker}")

    release_readiness = _read(release_readiness_path)
    for marker in ("check_requirements_resolution.py", "check_hostinger_readiness.py", "docker_build_smoke.py"):
        if marker not in release_readiness:
            errors.append(f"scripts/release_readiness.py missing marker: {marker}")

    import_smoke = _read(import_smoke_path)
    for marker in ("CORE_RUNTIME_IMPORTS", "HEAVY_RUNTIME_IMPORTS", "--include-heavy", "faster_whisper", "duckduckgo_search", "Runtime import smoke OK"):
        if marker not in import_smoke:
            errors.append(f"scripts/runtime_import_smoke.py missing marker: {marker}")

    vps_prereqs = _read(vps_prereqs_path)
    for marker in ("--skip-models", "docker compose version", "docker info", "python3", "rsync", "curl", "MODEL_PROVIDER", "EMBEDDING_PROVIDER"):
        if marker not in vps_prereqs:
            errors.append(f"scripts/check_vps_prereqs.sh missing marker: {marker}")

    post_deploy = _read(post_deploy_path)
    for marker in ("docker compose config", "docker compose ps", "pg_isready", "redis-cli", "docker compose logs bot"):
        if marker not in post_deploy:
            errors.append(f"scripts/check_post_deploy_health.sh missing marker: {marker}")

    if errors:
        print("Runtime asset verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Runtime asset verification OK")
    return 0


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _requirement_names(requirements: str) -> set[str]:
    names: set[str] = set()
    for line in requirements.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for separator in ("==", ">=", "<=", "~=", ">", "<"):
            if separator in stripped:
                stripped = stripped.split(separator, 1)[0]
                break
        names.add(stripped.lower())
    return names


if __name__ == "__main__":
    raise SystemExit(main())
