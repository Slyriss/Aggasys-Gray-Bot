#!/usr/bin/env bash
set -euo pipefail

errors=()
warnings=()

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    errors+=("Missing required command: $name")
    return 1
  fi
  return 0
}

service_running() {
  local service="$1"
  docker compose ps --status running --services 2>/dev/null | grep -Fx "$service" >/dev/null 2>&1
}

container_health() {
  local service="$1"
  local container_id
  container_id="$(docker compose ps -q "$service" 2>/dev/null || true)"
  if [ -z "$container_id" ]; then
    echo "missing"
    return
  fi
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || echo "unknown"
}

echo "Checking Gray post-deploy health..."

require_command docker
require_command python3

if [ ! -f .env ]; then
  errors+=(".env is missing. Create it from .env.example before deploy.")
fi

if ((${#errors[@]} == 0)); then
  if ! python3 bot/preflight.py --env-file .env >/tmp/gray-postdeploy-preflight.txt 2>&1; then
    errors+=("Gray/Hermes preflight failed. Output: $(tr '\n' ' ' </tmp/gray-postdeploy-preflight.txt)")
  fi

  if ! docker compose config >/dev/null 2>&1; then
    errors+=("Docker Compose config is invalid.")
  fi

  for service in postgres redis bot; do
    if ! service_running "$service"; then
      errors+=("Service is not running: $service")
    fi
  done

  for service in postgres redis; do
    health="$(container_health "$service")"
    if [ "$health" != "healthy" ]; then
      errors+=("Service $service health is $health, expected healthy.")
    fi
  done

  if ! docker compose exec -T postgres pg_isready -U aggasys -d aggasys >/dev/null 2>&1; then
    errors+=("Postgres did not answer pg_isready.")
  fi

  if ! docker compose exec -T redis redis-cli ping 2>/dev/null | grep -Fx "PONG" >/dev/null 2>&1; then
    errors+=("Redis did not answer PONG.")
  fi

  docker compose logs bot --tail=160 >/tmp/gray-postdeploy-bot.log 2>&1 || {
    errors+=("Could not read bot logs.")
  }

  if [ -f /tmp/gray-postdeploy-bot.log ]; then
    if grep -E "Traceback|CRITICAL|ERROR|Unhandled exception|SystemExit|password authentication failed|Hermes scheduler tick failed" /tmp/gray-postdeploy-bot.log >/dev/null 2>&1; then
      errors+=("Bot logs contain a fatal-looking error. Run: docker compose logs bot -f")
    fi
    if ! grep -E "Aggasys second brain starting|Hermes scheduler started|Application started|polling" /tmp/gray-postdeploy-bot.log >/dev/null 2>&1; then
      warnings+=("Bot logs did not include the usual startup markers in the last 160 lines.")
    fi
  fi
fi

rm -f /tmp/gray-postdeploy-preflight.txt /tmp/gray-postdeploy-bot.log

if ((${#warnings[@]})); then
  echo
  echo "Warnings:"
  for warning in "${warnings[@]}"; do
    printf -- '- %s\n' "$warning"
  done
fi

if ((${#errors[@]})); then
  echo
  echo "Post-deploy health check failed:"
  for error in "${errors[@]}"; do
    printf -- '- %s\n' "$error"
  done
  exit 1
fi

echo
echo "Post-deploy health check OK"
