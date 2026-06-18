#!/bin/sh
set -eu

APP_ROOT="${APP_ROOT:-$HOME/services/llm-wiki-app}"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:8080/health}"

cd "$APP_ROOT"
docker compose exec -T api llm-wiki ops-health \
  --api-url "$API_HEALTH_URL" \
  --backup-dir /backups \
  --codex-login-log /backups/codex-login-status.log \
  --exit-status \
  </dev/null
