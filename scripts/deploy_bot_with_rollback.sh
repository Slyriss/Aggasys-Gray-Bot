#!/usr/bin/env bash
# Build and restart the bot service, rolling back to the previous image on failed health.

set -euo pipefail

ROLLBACK_IMAGE=${ROLLBACK_IMAGE:-aggasys-bot-bot:rollback}
SETTLE_SECONDS=${SETTLE_SECONDS:-12}
HEALTH_SINCE_SECONDS=${HEALTH_SINCE_SECONDS:-90}

previous_image="$(docker compose images -q bot 2>/dev/null | head -n 1 || true)"
if [ -n "$previous_image" ]; then
  docker tag "$previous_image" "$ROLLBACK_IMAGE"
  echo "Tagged previous bot image for rollback."
else
  echo "No previous bot image found; rollback image unavailable."
fi

docker compose up -d --build bot
sleep "$SETTLE_SECONDS"

if bash scripts/check_post_deploy_health.sh --since "$HEALTH_SINCE_SECONDS"; then
  echo "New bot image passed post-deploy health."
  exit 0
fi

echo "New bot image failed health; attempting rollback." >&2
if [ -z "$previous_image" ]; then
  echo "Rollback unavailable: no previous bot image was found before deploy." >&2
  exit 1
fi

docker tag "$ROLLBACK_IMAGE" aggasys-bot-bot:latest
docker compose up -d --no-build bot
sleep "$SETTLE_SECONDS"

if bash scripts/check_post_deploy_health.sh --since "$HEALTH_SINCE_SECONDS"; then
  echo "Rollback completed and previous bot image is healthy." >&2
  exit 1
fi

echo "Rollback attempted but previous bot image did not pass health." >&2
exit 1
