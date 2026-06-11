# Deploy-ToVM.ps1 — Push GrayBot to the VM and deploy it
# Run from Windows when connected to the office network or VPN
# Usage: Right-click → "Run with PowerShell"  OR  powershell -File Deploy-ToVM.ps1

$VM_USER = "sean"
$VM_HOST = "172.16.10.50"
$VM_DIR  = "~/aggasys-bot"
$LOCAL_DIR = $PSScriptRoot

function Write-Step($msg) { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[x] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   Aggasys Second Brain — Deploy      ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. Check SSH is available ─────────────────────────────────────
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Fail "ssh not found. Enable OpenSSH in Windows Settings → Apps → Optional Features."
    exit 1
}

# ── 2. Test connectivity ──────────────────────────────────────────
Write-Step "Testing connection to ${VM_HOST}..."
$ping = Test-Connection -ComputerName $VM_HOST -Count 1 -Quiet -ErrorAction SilentlyContinue
if (-not $ping) {
    Write-Fail "Cannot reach $VM_HOST."
    Write-Host ""
    Write-Host "  Make sure you are:" -ForegroundColor Yellow
    Write-Host "  1. On the office network (Ethernet or WiFi), OR" -ForegroundColor Yellow
    Write-Host "  2. Connected via CorpLink VPN with routing to 172.16.10.x" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Current network: check 'ipconfig' for your 172.16.x.x address" -ForegroundColor Yellow
    exit 1
}
Write-Step "VM is reachable."

# ── 3. Check .env ─────────────────────────────────────────────────
$envFile = Join-Path $LOCAL_DIR ".env"
if (-not (Test-Path $envFile)) {
    Write-Fail ".env file not found at $envFile"
    exit 1
}

$envContent = Get-Content $envFile -Raw
if ($envContent -match "DB_PASS=changeme_strong_password") {
    Write-Warn "DB_PASS is still the default! Edit .env before deploying to production."
    $confirm = Read-Host "Continue anyway? [y/N]"
    if ($confirm -ne "y") { exit 0 }
}

$allowedUsers = ($envContent | Select-String "^ALLOWED_USERS=(.*)").Matches.Groups[1].Value.Trim()
if ([string]::IsNullOrEmpty($allowedUsers)) {
    Write-Warn "ALLOWED_USERS is empty — bot will be accessible to anyone with the link."
}

# ── 4. Sync files to VM ───────────────────────────────────────────
Write-Step "Syncing project files to $VM_USER@${VM_HOST}:$VM_DIR ..."

# Use rsync if available, otherwise fall back to scp
if (Get-Command rsync -ErrorAction SilentlyContinue) {
    rsync -avz --progress `
        --exclude=".git" `
        --exclude="__pycache__" `
        --exclude="*.pyc" `
        "${LOCAL_DIR}/" `
        "${VM_USER}@${VM_HOST}:${VM_DIR}/"
} else {
    # scp fallback — create directory first
    ssh "${VM_USER}@${VM_HOST}" "mkdir -p $VM_DIR"

    # Copy main files
    scp -r "${LOCAL_DIR}/bot" "${VM_USER}@${VM_HOST}:${VM_DIR}/"
    scp "${LOCAL_DIR}/docker-compose.yml"  "${VM_USER}@${VM_HOST}:${VM_DIR}/"
    scp "${LOCAL_DIR}/init.sql"            "${VM_USER}@${VM_HOST}:${VM_DIR}/"
    scp "${LOCAL_DIR}/migration.sql"       "${VM_USER}@${VM_HOST}:${VM_DIR}/"
    scp "${LOCAL_DIR}/deploy.sh"           "${VM_USER}@${VM_HOST}:${VM_DIR}/"
    scp "${LOCAL_DIR}/.env"                "${VM_USER}@${VM_HOST}:${VM_DIR}/"
}

# ── 5. Run deploy.sh on the VM ────────────────────────────────────
Write-Step "Running deploy.sh on the VM..."
$deployMode = Read-Host "Fresh install or upgrade? [fresh/upgrade] (default: upgrade)"
if ([string]::IsNullOrEmpty($deployMode)) { $deployMode = "upgrade" }

ssh "${VM_USER}@${VM_HOST}" "chmod +x $VM_DIR/deploy.sh && bash $VM_DIR/deploy.sh $deployMode"

Write-Host ""
Write-Step "Deployment complete!"
Write-Host ""
Write-Host "  To follow logs:" -ForegroundColor Cyan
Write-Host "    ssh ${VM_USER}@${VM_HOST}" -ForegroundColor White
Write-Host "    cd $VM_DIR && docker compose logs bot -f" -ForegroundColor White
Write-Host ""
