#!/usr/bin/env bash
set -euo pipefail

SKIP_MODELS=0
if [ "${1:-}" = "--skip-models" ]; then
  SKIP_MODELS=1
elif [ "${1:-}" != "" ]; then
  echo "Usage: bash scripts/check_vps_prereqs.sh [--skip-models]" >&2
  exit 2
fi

read_env() {
  local key="$1"
  local default_value="${2:-}"
  if [ -f .env ]; then
    local value
    value="$(grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2- || true)"
    if [ -n "$value" ]; then
      printf '%s' "$value"
      return 0
    fi
  fi
  printf '%s' "$default_value"
}

MODEL_PROVIDER="$(read_env MODEL_PROVIDER "${MODEL_PROVIDER:-deepseek}")"
EMBEDDING_PROVIDER="$(read_env EMBEDDING_PROVIDER "${EMBEDDING_PROVIDER:-disabled}")"
NEEDS_OLLAMA=0
if [ "$MODEL_PROVIDER" = "ollama" ] || [ "$EMBEDDING_PROVIDER" = "ollama" ]; then
  NEEDS_OLLAMA=1
fi

REQUIRED_MODELS=(
  "$(read_env OLLAMA_MODEL "${OLLAMA_MODEL:-qwen2.5:3b}")"
  "$(read_env EMBED_MODEL "${EMBED_MODEL:-nomic-embed-text}")"
)

errors=()
warnings=()

require_command() {
  local name="$1"
  local hint="$2"

  if ! command -v "$name" >/dev/null 2>&1; then
    errors+=("Missing $name. $hint")
    return 1
  fi

  return 0
}

print_version() {
  local label="$1"
  shift

  if "$@" >/tmp/gray-prereq-version.txt 2>&1; then
    printf '%s: %s\n' "$label" "$(head -n 1 /tmp/gray-prereq-version.txt)"
  else
    warnings+=("Could not read $label version.")
  fi
}

echo "Checking Gray VPS prerequisites..."

if require_command docker "Install Docker Engine before deploying."; then
  print_version "Docker" docker --version

  if docker compose version >/tmp/gray-prereq-compose.txt 2>&1; then
    printf 'Docker Compose: %s\n' "$(head -n 1 /tmp/gray-prereq-compose.txt)"
  else
    errors+=("Docker Compose plugin is unavailable. Install the Docker Compose plugin, not only legacy docker-compose.")
  fi

  if ! docker info >/dev/null 2>&1; then
    warnings+=("Docker is installed but the daemon is not reachable for this user.")
  fi
fi

if require_command python3 "Install Python 3 for preflight and repository checks."; then
  print_version "Python" python3 --version
fi

if require_command rsync "Install rsync for deploy synchronization."; then
  print_version "rsync" rsync --version
fi

require_command curl "Install curl for local health checks."

if [ "$NEEDS_OLLAMA" -eq 0 ]; then
  warnings+=("Ollama not required for MODEL_PROVIDER=$MODEL_PROVIDER and EMBEDDING_PROVIDER=$EMBEDDING_PROVIDER.")
elif require_command ollama "Install Ollama on the VPS host or set EMBEDDING_PROVIDER=disabled and MODEL_PROVIDER=deepseek."; then
  print_version "Ollama" ollama --version

  if command -v curl >/dev/null 2>&1 && ! curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    warnings+=("Ollama CLI is installed but the local Ollama service is not answering on 127.0.0.1:11434.")
  fi

  if [ "$SKIP_MODELS" -eq 1 ]; then
    warnings+=("Skipping Ollama model presence checks.")
  elif ollama list >/tmp/gray-prereq-models.txt 2>&1; then
    for model in "${REQUIRED_MODELS[@]}"; do
      if ! awk '{print $1}' /tmp/gray-prereq-models.txt | grep -Fx "$model" >/dev/null 2>&1; then
        errors+=("Missing Ollama model: $model. Run: ollama pull $model")
      fi
    done
  else
    errors+=("Could not list Ollama models. Start Ollama, then rerun this check.")
  fi
fi

rm -f /tmp/gray-prereq-version.txt /tmp/gray-prereq-compose.txt /tmp/gray-prereq-models.txt

if ((${#warnings[@]})); then
  echo
  echo "Warnings:"
  for warning in "${warnings[@]}"; do
    printf -- '- %s\n' "$warning"
  done
fi

if ((${#errors[@]})); then
  echo
  echo "VPS prerequisite check failed:"
  for error in "${errors[@]}"; do
    printf -- '- %s\n' "$error"
  done
  exit 1
fi

echo
echo "VPS prerequisite check OK"
