# VM Deploy Status

**Deployed:** Fri Jul 10 04:36:36 AM UTC 2026
**Commit:** 854a7eb3b054e562b5159da29a90732b9ecf8475

## Docker Services
```
NAME                     IMAGE                    COMMAND                  SERVICE    CREATED          STATUS                    PORTS
aggasys-bot-bot-1        aggasys-bot-bot          "python main.py"         bot        25 seconds ago   Up 20 seconds             
aggasys-bot-postgres-1   pgvector/pgvector:pg16   "docker-entrypoint.s…"   postgres   47 minutes ago   Up 47 minutes (healthy)   5432/tcp
aggasys-bot-redis-1      redis:alpine             "docker-entrypoint.s…"   redis      41 minutes ago   Up 41 minutes (healthy)   6379/tcp
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
HERMES_GROUP_CHAT_MODE
HERMES_TIMEZONE
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
...................................................................................................................
----------------------------------------------------------------------
Ran 115 tests in 0.631s

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
