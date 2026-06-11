#!/bin/bash
# push_to_vm.sh — Run this on YOUR LOCAL MACHINE to push files to the VM
# Requires: SSH access to 172.16.10.50 (be on office network or VPN)
# Usage: bash push_to_vm.sh

VM_USER="sean"
VM_HOST="172.16.10.50"
VM_DIR="~/aggasys-bot"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Pushing project to $VM_USER@$VM_HOST:$VM_DIR"

# Test connection first
ssh -o ConnectTimeout=5 "$VM_USER@$VM_HOST" "echo ok" 2>/dev/null || {
    echo -e "${RED}[✗]${NC} Cannot reach $VM_HOST — connect to the office network or VPN first."
    exit 1
}

# Sync files (excludes git history, Python cache, local .env override)
rsync -avz --progress \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    "$SCRIPT_DIR/" \
    "$VM_USER@$VM_HOST:$VM_DIR/"

info "Files synced."

# Prompt to also push .env (optional — may want to manage separately)
read -p "Also push .env file? [y/N] " PUSH_ENV
if [[ "$PUSH_ENV" =~ ^[Yy]$ ]]; then
    scp "$SCRIPT_DIR/.env" "$VM_USER@$VM_HOST:$VM_DIR/.env"
    info ".env pushed."
fi

info ""
info "Now run on the VM:"
info "  ssh $VM_USER@$VM_HOST"
info "  cd $VM_DIR && bash deploy.sh upgrade"
