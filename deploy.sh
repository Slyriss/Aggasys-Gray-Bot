#!/bin/bash
# deploy.sh — Run this ON the VM to deploy/upgrade Aggasys second brain
# Usage: bash deploy.sh [fresh|upgrade]
# "fresh"   = first-time install (drops nothing, init.sql runs via Docker)
# "upgrade" = existing install, runs migration.sql then rebuilds

set -e
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
info "Checking prerequisites..."
command -v docker  >/dev/null || error "docker not found"
command -v ollama  >/dev/null || error "ollama not found — install from ollama.com"

# ── 2. Pull required Ollama models ──────────────────────────────
info "Checking Ollama models..."

if ollama list | grep -q "qwen2.5:3b"; then
    info "qwen2.5:3b already present"
else
    warn "Pulling qwen2.5:3b (this may take a few minutes)..."
    ollama pull qwen2.5:3b
fi

if ollama list | grep -q "nomic-embed-text"; then
    info "nomic-embed-text already present"
else
    warn "Pulling nomic-embed-text (required for semantic search)..."
    ollama pull nomic-embed-text
fi

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
    sleep 5  # wait for postgres to be ready

    # Check if migration is needed (test for company_memory table)
    TABLES=$(docker compose exec -T postgres psql -U aggasys -d aggasys -tAc \
        "SELECT tablename FROM pg_tables WHERE schemaname='public'" 2>/dev/null || echo "")

    if echo "$TABLES" | grep -q "company_memory"; then
        info "Migration already applied — company_memory table exists"
    else
        info "Applying migration.sql..."
        docker compose exec -T postgres psql -U aggasys -d aggasys < migration.sql
        info "Migration complete"
    fi
fi

# ── 6. Build and start ───────────────────────────────────────────
info "Building Docker image and starting services..."
docker compose up -d --build

# ── 7. Verify ────────────────────────────────────────────────────
info "Waiting for services to settle (15s)..."
sleep 15

info "Checking service health..."
docker compose ps

BOT_STATUS=$(docker compose ps bot --format json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('State','unknown'))" 2>/dev/null || echo "unknown")

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
