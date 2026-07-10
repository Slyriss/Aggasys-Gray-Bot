#!/bin/bash
# deploy.sh — Run this ON the VM to deploy/upgrade Aggasys second brain
# Usage: bash deploy.sh [fresh|upgrade]
# "fresh"   = first-time install (drops nothing, init.sql runs via Docker)
# "upgrade" = existing install, runs migration.sql then rebuilds

set -euo pipefail
MODE=${1:-upgrade}
DEPLOY_DIR="$HOME/aggasys-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Aggasys Second Brain — Deploy      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── 1. Pre-flight checks ─────────────────────────────────────────
case "$MODE" in
    fresh|upgrade) ;;
    *) error "Unknown deploy mode '$MODE'. Usage: bash deploy.sh [fresh|upgrade]" ;;
esac

info "Checking prerequisites..."
bash scripts/check_vps_prereqs.sh --skip-models || error "VPS prerequisite check failed"

# ── 3. Copy project files ────────────────────────────────────────
if [ "$SCRIPT_DIR" != "$DEPLOY_DIR" ]; then
    info "Copying project to $DEPLOY_DIR..."
    mkdir -p "$DEPLOY_DIR"
    rsync -av --exclude='.git' --exclude='__pycache__' \
        "$SCRIPT_DIR/" "$DEPLOY_DIR/"
fi
cd "$DEPLOY_DIR"

# ── 4. Check .env ────────────────────────────────────────────────
if [ ! -f .env ]; then
    error ".env file not found. Create it from the template in the project."
fi

info "Running Gray/Hermes preflight..."
python3 bot/preflight.py --env-file .env || error "Preflight failed. Fix .env before deploying."

MODEL_PROVIDER=$(grep "^MODEL_PROVIDER=" .env | cut -d= -f2 | tr -d ' ' || true)
EMBEDDING_PROVIDER=$(grep "^EMBEDDING_PROVIDER=" .env | cut -d= -f2 | tr -d ' ' || true)
MODEL_PROVIDER=${MODEL_PROVIDER:-deepseek}
EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER:-disabled}

# ── 4b. Pull required Ollama models when local inference/embeddings are enabled ──
if [ "$MODEL_PROVIDER" = "ollama" ] || [ "$EMBEDDING_PROVIDER" = "ollama" ]; then
    info "Checking Ollama models..."
    OLLAMA_MODEL=$(grep "^OLLAMA_MODEL=" .env | cut -d= -f2 | tr -d ' ' || true)
    EMBED_MODEL=$(grep "^EMBED_MODEL=" .env | cut -d= -f2 | tr -d ' ' || true)
    OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:3b}
    EMBED_MODEL=${EMBED_MODEL:-nomic-embed-text}

    if ollama list | awk '{print $1}' | grep -Fx "$OLLAMA_MODEL" >/dev/null 2>&1; then
        info "$OLLAMA_MODEL already present"
    else
        warn "Pulling $OLLAMA_MODEL (this may take a few minutes)..."
        ollama pull "$OLLAMA_MODEL"
    fi

    if [ "$EMBEDDING_PROVIDER" = "ollama" ]; then
        if ollama list | awk '{print $1}' | grep -Fx "$EMBED_MODEL" >/dev/null 2>&1; then
            info "$EMBED_MODEL already present"
        else
            warn "Pulling $EMBED_MODEL (required for semantic search)..."
            ollama pull "$EMBED_MODEL"
        fi
    fi

    bash scripts/check_vps_prereqs.sh || error "VPS prerequisite check failed after model pull"
else
    info "Skipping Ollama model pull for MODEL_PROVIDER=$MODEL_PROVIDER EMBEDDING_PROVIDER=$EMBEDDING_PROVIDER"
fi

info "Running local verification checks..."
python3 scripts/check_in_venv.py --venv .venv-deploy || error "Local verification failed. Fix checks before deploying."

info "Validating Docker Compose config..."
docker compose config >/dev/null || error "Docker Compose config is invalid."

# Warn if ALLOWED_USERS is empty
ALLOWED=$(grep "^ALLOWED_USERS=" .env | cut -d= -f2 | tr -d ' ')
if [ -z "$ALLOWED" ]; then
    warn "ALLOWED_USERS is empty — bot is open to everyone. Add your Telegram ID to .env"
fi

# Warn if DB_PASS is default
DBPASS=$(grep "^DB_PASS=" .env | cut -d= -f2)
if [ "$DBPASS" = "changeme_strong_password" ]; then
    warn "DB_PASS is still the default! Change it in .env before running in production."
fi

# ── 5. Handle database ───────────────────────────────────────────
if [ "$MODE" = "fresh" ]; then
    info "Fresh install — init.sql will run automatically via Docker entrypoint"
elif [ "$MODE" = "upgrade" ]; then
    info "Upgrade mode — running migration.sql on existing database..."
    # Start only postgres to run migration
    docker compose up -d postgres
    info "Waiting for Postgres healthcheck..."
    for attempt in $(seq 1 30); do
        if docker compose exec -T postgres pg_isready -U aggasys -d aggasys >/dev/null 2>&1; then
            break
        fi
        if [ "$attempt" -eq 30 ]; then
            error "Postgres did not become ready in time."
        fi
        sleep 2
    done

    info "Backing up Hermes operational data..."
    bash scripts/backup_hermes_data.sh backups || error "Hermes data backup failed. Migration not started."

    info "Applying idempotent migration.sql..."
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U aggasys -d aggasys < migration.sql
    info "Migration complete"
fi

# ── 6. Build and start ───────────────────────────────────────────
info "Building Docker image and starting services..."
docker compose up -d --build

# ── 7. Verify ────────────────────────────────────────────────────
info "Waiting for services to settle (15s)..."
sleep 15

info "Checking service health..."
docker compose ps

info "Running post-deploy health check..."
bash scripts/check_post_deploy_health.sh || error "Post-deploy health check failed."

echo ""
if docker compose logs bot --tail=20 2>&1 | grep -q "Aggasys second brain starting\|polling"; then
    echo -e "${GREEN}✅ Bot is running!${NC}"
else
    echo -e "${YELLOW}⚠  Check logs:${NC} docker compose logs bot -f"
fi

echo ""
echo "  Quick commands:"
echo "    Logs:     docker compose logs bot -f"
echo "    Restart:  docker compose restart bot"
echo "    Stop:     docker compose down"
echo ""
info "Done."
