# VM Deploy Status

**Deployed:** Fri Jul 10 05:46:10 AM UTC 2026
**Commit:** a8216ead0a17fc79540843d59606ab413ad292be

## Docker Services
```
NAME                     IMAGE                    COMMAND                  SERVICE    CREATED          STATUS                 PORTS
aggasys-bot-bot-1        aggasys-bot-bot          "python main.py"         bot        25 seconds ago   Up 20 seconds          
aggasys-bot-postgres-1   pgvector/pgvector:pg16   "docker-entrypoint.s…"   postgres   2 hours ago      Up 2 hours (healthy)   5432/tcp
aggasys-bot-redis-1      redis:alpine             "docker-entrypoint.s…"   redis      2 hours ago      Up 2 hours (healthy)   6379/tcp
```

## Bot Logs (last 30 lines)
```
bot-1  | WARNING:__main__:Preflight: OLLAMA_URL points at localhost. In Docker Compose deploys use http://host.docker.internal:11434 so the bot container can reach host Ollama.
bot-1  | INFO:__main__:Aggasys second brain starting...
bot-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot***/getMe "HTTP/1.1 200 OK"
bot-1  | INFO:hermes.scheduler:Hermes scheduler started interval=30s
bot-1  | INFO:__main__:Memory queue started workers=1
bot-1  | INFO:__main__:Allowlist active: {1143441908}
bot-1  | INFO:__main__:Admin role active: {1143441908}
bot-1  | INFO:__main__:Rate limit active: 30 messages per 60s
bot-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot***/deleteWebhook "HTTP/1.1 200 OK"
bot-1  | INFO:telegram.ext.Application:Application started
bot-1  | INFO:httpx:HTTP Request: POST https://api.telegram.org/bot***/getUpdates "HTTP/1.1 200 OK"
```

## Model Backend
```
MODEL_PROVIDER=deepseek
EMBEDDING_PROVIDER=disabled
NAME                       ID              SIZE      MODIFIED    
nomic-embed-text:latest    0a109f422b47    274 MB    4 weeks ago    
qwen2.5:3b                 357c53fb659c    1.9 GB    4 weeks ago    
```

## .env Keys Present (no values)
```
ADMIN_USERS
ALLOWED_USERS
DATABASE_URL
DB_PASS
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
EMBEDDING_PROVIDER
GRAY_BOT_USERNAME
HERMES_AUDIT_RETENTION_DAYS
HERMES_BACKUP_RETENTION_DAYS
HERMES_GROUP_CHAT_MODE
HERMES_OPERATION_RETENTION_DAYS
HERMES_TIMEZONE
MAX_DOCUMENT_BYTES
MAX_PHOTO_BYTES
MAX_VOICE_BYTES
MODEL_PROVIDER
OLLAMA_MODEL
OLLAMA_URL
RATE_LIMIT_MESSAGES
RATE_LIMIT_WINDOW_SECONDS
REDIS_URL
TELEGRAM_TOKEN
```

## Gray/Hermes Verification Gates
```
.........WARNING:main:Telegram Markdown rejected; retrying message as plain text.
.........WARNING:main:Telegram Markdown rejected; retrying message as plain text.
...............................................................................................................................INFO:url_ingester:Blocking URL host internal.example.com resolved to non-public address 192.168.1.10
..INFO:url_ingester:Blocked unsafe URL redirect target: http://127.0.0.1/admin
..
----------------------------------------------------------------------
Ran 149 tests in 0.587s

OK
Command surface verification OK
Deployment asset verification OK
Release readiness OK
Docker build smoke skipped. Run with --include-docker when Docker is available.
Release readiness OK
+ /usr/bin/python3 -m unittest discover -s tests
+ /usr/bin/python3 -m compileall -q bot tests scripts
+ /usr/bin/python3 scripts/scan_secret_hygiene.py
+ /usr/bin/python3 scripts/runtime_import_smoke.py
+ /usr/bin/python3 scripts/verify_deployment_assets.py
+ /usr/bin/python3 scripts/verify_runtime_assets.py
+ /usr/bin/python3 scripts/verify_schema_assets.py
+ /usr/bin/python3 scripts/verify_policy_registry.py
+ /usr/bin/python3 scripts/verify_command_surface.py
All local checks passed
Runtime import smoke OK
Secret hygiene scan OK
Runtime import smoke OK
Deployment asset verification OK
Runtime asset verification OK
Schema asset verification OK
Hermes policy registry verification OK
Command surface verification OK
+ /usr/bin/python3 -m unittest discover -s tests
+ /usr/bin/python3 -m compileall -q bot tests scripts
+ /usr/bin/python3 scripts/scan_secret_hygiene.py
+ /usr/bin/python3 scripts/runtime_import_smoke.py
+ /usr/bin/python3 scripts/verify_deployment_assets.py
+ /usr/bin/python3 scripts/verify_runtime_assets.py
+ /usr/bin/python3 scripts/verify_schema_assets.py
+ /usr/bin/python3 scripts/verify_policy_registry.py
+ /usr/bin/python3 scripts/verify_command_surface.py
All local checks passed
```

## Gray/Hermes Preflight
```
Gray/Hermes preflight
Warnings:
- OLLAMA_URL points at localhost. In Docker Compose deploys use http://host.docker.internal:11434 so the bot container can reach host Ollama.
Status: OK
```

## Post-Deploy Health
```
Checking Gray post-deploy health...

Post-deploy health check OK
```
