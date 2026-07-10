from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    ".env.example",
    "docker-compose.yml",
    "init.sql",
    "migration.sql",
    "deploy.sh",
    "bot/preflight.py",
    "bot/model_client.py",
    "bot/hermes/scheduler.py",
    "bot/hermes/monitoring.py",
    "bot/hermes/jobs.py",
    "bot/.dockerignore",
    "docs/HOSTINGER_DEPLOYMENT.md",
    "docs/TELEGRAM_SMOKE_TEST.md",
    "scripts/check_hostinger_readiness.py",
    "scripts/check_vps_prereqs.sh",
    "scripts/check_post_deploy_health.sh",
    "scripts/create_env_from_example.py",
    "scripts/check_requirements_resolution.py",
    "scripts/check_in_venv.py",
    "scripts/release_readiness.py",
    "scripts/scan_secret_hygiene.py",
    "scripts/docker_build_smoke.py",
    "scripts/runtime_import_smoke.py",
    "scripts/verify_deploy_status.py",
    "scripts/verify_runtime_assets.py",
    "scripts/verify_schema_assets.py",
    "scripts/verify_policy_registry.py",
    "scripts/verify_command_surface.py",
    "scripts/backup_hermes_data.sh",
    "scripts/restore_hermes_data.sh",
]

REQUIRED_MIGRATION_MARKERS = [
    "CREATE TABLE IF NOT EXISTS hermes_audit_log",
    "CREATE TABLE IF NOT EXISTS hermes_approval_requests",
    "ALTER TABLE hermes_approval_requests ADD COLUMN IF NOT EXISTS expires_at",
    "CREATE INDEX IF NOT EXISTS idx_hermes_approvals_expiry",
    "CREATE TABLE IF NOT EXISTS hermes_jobs",
    "CREATE TABLE IF NOT EXISTS standup_sessions",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS last_error",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS consecutive_failures",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS locked_at",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS payload",
    "ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS updated_at",
]

REQUIRED_DEPLOY_SCRIPT_MARKERS = [
    "Unknown deploy mode '$MODE'. Usage: bash deploy.sh [fresh|upgrade]",
    "set -euo pipefail",
    "bash scripts/check_vps_prereqs.sh --skip-models",
    "bash scripts/check_vps_prereqs.sh || error",
    "python3 bot/preflight.py --env-file .env",
    "python3 scripts/check_in_venv.py --venv .venv-deploy",
    "docker compose config >/dev/null",
    "pg_isready -U aggasys -d aggasys",
    "bash scripts/backup_hermes_data.sh backups",
    "docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U aggasys -d aggasys < migration.sql",
    "bash scripts/check_post_deploy_health.sh",
]

REQUIRED_WORKFLOW_MARKERS = [
    "bash scripts/check_vps_prereqs.sh --skip-models",
    "bash scripts/check_vps_prereqs.sh",
    "python3 bot/preflight.py --env-file .env",
    "python3 -m pip install --user -r bot/requirements.txt",
    "python3 scripts/run_checks.py",
    "docker compose config >/dev/null",
    "pg_isready -U aggasys -d aggasys",
    "bash scripts/backup_hermes_data.sh backups",
    "docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U aggasys -d aggasys < migration.sql",
    "bash scripts/check_post_deploy_health.sh",
    "python3 scripts/verify_deploy_status.py DEPLOY_STATUS.md",
]

FORBIDDEN_DEPLOY_MARKERS = [
    "docker compose exec -T postgres psql -U aggasys -d aggasys < migration.sql || true",
    "docker compose exec -T postgres psql -U aggasys -d aggasys < migration.sql",
]

REQUIRED_COMMAND_MARKERS = [
    "standup_chase_schedule",
    "monitor_schedule",
    "schedule_pause",
    "schedule_resume",
    "schedule_remove",
]


def main() -> int:
    errors: list[str] = []

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            errors.append(f"Missing required deployment file: {rel}")

    gitignore = _read(".gitignore")
    for marker in (".env", ".env.*", "!.env.example", "backups/", "DEPLOY_STATUS.md"):
        if marker not in gitignore:
            errors.append(f".gitignore missing marker: {marker}")
    if ".venv/" not in gitignore:
        errors.append(".gitignore missing marker: .venv/")
    if ".venv-deploy/" not in gitignore:
        errors.append(".gitignore missing marker: .venv-deploy/")

    migration = _read("migration.sql")
    for marker in REQUIRED_MIGRATION_MARKERS:
        if marker not in migration:
            errors.append(f"migration.sql missing marker: {marker}")
    _require_order(
        migration,
        "ALTER TABLE hermes_approval_requests ADD COLUMN IF NOT EXISTS expires_at",
        "CREATE INDEX IF NOT EXISTS idx_hermes_approvals_expiry",
        "migration.sql must add hermes approval expires_at before creating its index.",
        errors,
    )

    deploy = _read("deploy.sh")
    for marker in REQUIRED_DEPLOY_SCRIPT_MARKERS:
        if marker not in deploy:
            errors.append(f"deploy.sh missing marker: {marker}")
    workflow = _read(".github/workflows/deploy.yml")
    for marker in REQUIRED_WORKFLOW_MARKERS:
        if marker not in workflow:
            errors.append(f".github/workflows/deploy.yml missing marker: {marker}")
    for marker in FORBIDDEN_DEPLOY_MARKERS:
        if marker in deploy:
            errors.append(f"deploy.sh contains forbidden marker: {marker}")
        if marker in workflow:
            errors.append(f".github/workflows/deploy.yml contains forbidden marker: {marker}")

    compose = _read("docker-compose.yml")
    if "network_mode: host" in compose:
        errors.append("docker-compose.yml should not use host networking for the bot service.")
    if "host.docker.internal:host-gateway" not in compose:
        errors.append("docker-compose.yml missing host.docker.internal extra_hosts mapping for Ollama.")
    for marker in ("pg_isready -U aggasys -d aggasys", "redis-cli\", \"ping", "condition: service_healthy"):
        if marker not in compose:
            errors.append(f"docker-compose.yml missing health marker: {marker}")
    if "postgres:\n    image: pgvector/pgvector:pg16\n    env_file:" in compose:
        errors.append("postgres service should not receive the full bot .env file.")
    for public_port in ('"5432:5432"', '"6379:6379"', "'5432:5432'", "'6379:6379'"):
        if public_port in compose:
            errors.append(f"docker-compose.yml should not publicly publish {public_port}.")

    env_example = _read(".env.example")
    for marker in (
        "MODEL_PROVIDER=deepseek",
        "DEEPSEEK_API_KEY=replace_with_deepseek_api_key",
        "DEEPSEEK_BASE_URL=https://api.deepseek.com",
        "DEEPSEEK_MODEL=deepseek-v4-flash",
        "EMBEDDING_PROVIDER=disabled",
    ):
        if marker not in env_example:
            errors.append(f".env.example missing DeepSeek VM marker: {marker}")
    if "HERMES_JOB_FAILURE_LIMIT=3" not in env_example:
        errors.append(".env.example missing HERMES_JOB_FAILURE_LIMIT.")
    preflight = _read("bot/preflight.py")
    for marker in ("ALLOWED_USERS", "MODEL_PROVIDER", "DEEPSEEK_API_KEY", "EMBEDDING_PROVIDER", "HERMES_TIMEZONE", "ZoneInfo"):
        if marker not in preflight:
            errors.append(f"bot/preflight.py missing strict env marker: {marker}")
    model_client = _read("bot/model_client.py")
    for marker in ("DEEPSEEK_BASE_URL", "/chat/completions", "deepseek-v4-flash", "MODEL_PROVIDER"):
        if marker not in model_client:
            errors.append(f"bot/model_client.py missing DeepSeek marker: {marker}")

    main_py = _read("bot/main.py")
    for marker in REQUIRED_COMMAND_MARKERS:
        if marker not in main_py:
            errors.append(f"bot/main.py missing command marker: {marker}")

    db_py = _read("bot/db.py")
    for marker in ("HERMES_JOB_FAILURE_LIMIT", "status = CASE", "consecutive_failures + 1 >= $3", "RETURNING id, chat_id"):
        if marker not in db_py:
            errors.append(f"bot/db.py missing failed-job auto-pause marker: {marker}")
    scheduler = _read("bot/hermes/scheduler.py")
    for marker in ("scheduled_job_auto_paused", "_audit_job_auto_paused"):
        if marker not in scheduler:
            errors.append(f"bot/hermes/scheduler.py missing auto-pause audit marker: {marker}")
    policy = _read("bot/hermes/policy.py")
    for marker in ("READ_ONLY_ACTIONS", "INTERNAL_WORKFLOW_ACTIONS", "CONFIRMATION_REQUIRED", "Unknown Hermes action"):
        if marker not in policy:
            errors.append(f"bot/hermes/policy.py missing registry marker: {marker}")
    agent = _read("bot/agent.py")
    for marker in ("Hermes routing rules", "Never invent tool names", "Do not route requests to spend money"):
        if marker not in agent:
            errors.append(f"bot/agent.py missing Hermes router guardrail marker: {marker}")
    prompts = _read("bot/prompts.py")
    for marker in ("Hermes operating guardrails", "explicit approval through Hermes", "Supply ordering is intentionally not implemented yet"):
        if marker not in prompts:
            errors.append(f"bot/prompts.py missing Hermes system guardrail marker: {marker}")

    smoke = _read("docs/TELEGRAM_SMOKE_TEST.md")
    for marker in (
        "/hermes_status",
        "/standup_schedule",
        "/standup_chase_schedule",
        "/monitor_schedule",
        "/schedule_pause",
        "HERMES_GROUP_CHAT_MODE=mention",
    ):
        if marker not in smoke:
            errors.append(f"docs/TELEGRAM_SMOKE_TEST.md missing marker: {marker}")
    deployment_doc = _read("docs/HOSTINGER_DEPLOYMENT.md")
    if "docs/TELEGRAM_SMOKE_TEST.md" not in deployment_doc:
        errors.append("Hostinger deployment doc must link the Telegram smoke test checklist.")
    if "scripts/check_hostinger_readiness.py" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the readiness wrapper.")
    if "scripts/check_vps_prereqs.sh" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the VPS prerequisite checker.")
    if "scripts/check_post_deploy_health.sh" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the post-deploy health checker.")
    if "scripts/create_env_from_example.py" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the env creation helper.")
    if "scripts/verify_policy_registry.py" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the Hermes policy registry checker.")
    if "scripts/runtime_import_smoke.py --include-heavy" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the optional heavyweight runtime import smoke.")
    if "scripts/check_requirements_resolution.py" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the requirements resolution checker.")
    if "scripts/check_in_venv.py" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the venv check helper.")
    if "scripts/release_readiness.py" not in deployment_doc:
        errors.append("Hostinger deployment doc must mention the release readiness helper.")
    if "psql -v ON_ERROR_STOP=1" not in deployment_doc:
        errors.append("Hostinger deployment doc must show strict migration execution.")
    readme = _read("README.md")
    for marker in (
        "Aggasys Gray Bot",
        "Hermes-style control harness",
        "python scripts/release_readiness.py --include-heavy --include-docker",
        "The best time to deploy",
        "docs/TELEGRAM_SMOKE_TEST.md",
        "Supply ordering is intentionally not implemented yet",
    ):
        if marker not in readme:
            errors.append(f"README.md missing marker: {marker}")

    readiness = _read("scripts/check_hostinger_readiness.py")
    for marker in ("scripts/run_checks.py", "docker", "compose", "Refusing to overwrite existing .env"):
        if marker not in readiness:
            errors.append(f"scripts/check_hostinger_readiness.py missing marker: {marker}")
    env_helper = _read("scripts/create_env_from_example.py")
    for marker in ("secrets.token_urlsafe", "DATABASE_URL=postgresql://aggasys:", "quote(db_pass", ".env already exists"):
        if marker not in env_helper:
            errors.append(f"scripts/create_env_from_example.py missing marker: {marker}")
    prereqs = _read("scripts/check_vps_prereqs.sh")
    for marker in ("--skip-models", "docker compose version", "python3", "rsync", "curl", "MODEL_PROVIDER", "EMBEDDING_PROVIDER", "Ollama not required"):
        if marker not in prereqs:
            errors.append(f"scripts/check_vps_prereqs.sh missing marker: {marker}")
    post_deploy = _read("scripts/check_post_deploy_health.sh")
    for marker in ("bot/preflight.py --env-file .env", "docker compose ps --status running", "pg_isready", "redis-cli ping", "docker compose logs bot", "Post-deploy health check OK"):
        if marker not in post_deploy:
            errors.append(f"scripts/check_post_deploy_health.sh missing marker: {marker}")
    build_smoke = _read("scripts/docker_build_smoke.py")
    for marker in ("docker", "build", "bot/Dockerfile", "aggasys-gray-bot:smoke", "Docker engine is not reachable"):
        if marker not in build_smoke:
            errors.append(f"scripts/docker_build_smoke.py missing marker: {marker}")
    requirements_resolution = _read("scripts/check_requirements_resolution.py")
    for marker in ("--dry-run", "--ignore-installed", "Requirements resolution OK"):
        if marker not in requirements_resolution:
            errors.append(f"scripts/check_requirements_resolution.py missing marker: {marker}")
    venv_check = _read("scripts/check_in_venv.py")
    for marker in ("venv.EnvBuilder", "bot/requirements.txt", "scripts/run_checks.py", "Venv checks passed"):
        if marker not in venv_check:
            errors.append(f"scripts/check_in_venv.py missing marker: {marker}")
    release_readiness = _read("scripts/release_readiness.py")
    for marker in ("scripts/run_checks.py", "scripts/check_hostinger_readiness.py", "--include-docker", "Release readiness OK"):
        if marker not in release_readiness:
            errors.append(f"scripts/release_readiness.py missing marker: {marker}")
    secret_hygiene = _read("scripts/scan_secret_hygiene.py")
    for marker in ("TELEGRAM_TOKEN", "DATABASE_URL", "Real .env file must not be present", "Secret hygiene scan OK"):
        if marker not in secret_hygiene:
            errors.append(f"scripts/scan_secret_hygiene.py missing marker: {marker}")
    run_checks = _read("scripts/run_checks.py")
    if "scripts/scan_secret_hygiene.py" not in run_checks:
        errors.append("scripts/run_checks.py must run the secret hygiene scanner.")
    if "scripts/verify_deploy_status.py" not in run_checks:
        errors.append("scripts/run_checks.py must verify the deploy status artifact.")
    if "--skip-deploy-status" not in run_checks:
        errors.append("scripts/run_checks.py must support skipping deploy status verification during status generation.")
    workflow = _read(".github/workflows/deploy.yml")
    if "scripts/run_checks.py --skip-deploy-status" not in workflow:
        errors.append(".github/workflows/deploy.yml must skip deploy status verification while generating DEPLOY_STATUS.md.")
    if "git restore --staged --worktree DEPLOY_STATUS.md" not in workflow:
        errors.append(".github/workflows/deploy.yml must clean only generated deploy status before pulling.")
    if "rm -rf .venv-deploy" not in workflow:
        errors.append(".github/workflows/deploy.yml must clean generated deploy virtualenv before pulling.")
    deploy_status = _read("scripts/verify_deploy_status.py")
    for marker in ("TELEGRAM_TOKEN_RE", "RUNTIME_FAILURE_MARKERS", "REQUIRED_HEALTH_MARKERS", "Deploy status verification OK"):
        if marker not in deploy_status:
            errors.append(f"scripts/verify_deploy_status.py missing marker: {marker}")
    import_smoke = _read("scripts/runtime_import_smoke.py")
    for marker in ("CORE_RUNTIME_IMPORTS", "HEAVY_RUNTIME_IMPORTS", "importlib.import_module", "Runtime import smoke OK"):
        if marker not in import_smoke:
            errors.append(f"scripts/runtime_import_smoke.py missing marker: {marker}")
    policy_registry = _read("scripts/verify_policy_registry.py")
    for marker in ("_decide_and_audit", "TOOLS_SCHEMA", "_is_registered_action", "Hermes policy registry verification OK"):
        if marker not in policy_registry:
            errors.append(f"scripts/verify_policy_registry.py missing marker: {marker}")
    command_surface = _read("scripts/verify_command_surface.py")
    for marker in ("CommandHandler", "SMOKE_REQUIRED_COMMANDS", "supply_order", "Command surface verification OK"):
        if marker not in command_surface:
            errors.append(f"scripts/verify_command_surface.py missing marker: {marker}")

    if errors:
        print("Deployment asset verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Deployment asset verification OK")
    return 0


def _read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _require_order(text: str, first: str, second: str, message: str, errors: list[str]) -> None:
    first_pos = text.find(first)
    second_pos = text.find(second)
    if first_pos == -1 or second_pos == -1:
        return
    if first_pos > second_pos:
        errors.append(message)


if __name__ == "__main__":
    raise SystemExit(main())
