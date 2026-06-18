#!/bin/sh
set -eu

APP_ROOT="${APP_ROOT:-$HOME/services/llm-wiki-app}"
ENV_FILE="${ENV_FILE:-$APP_ROOT/.env}"
BACKUP_DIR="${BACKUP_DIR:-$APP_ROOT/backups}"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:8080/health}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8080}"
SMOKE_SOURCE="${SMOKE_SOURCE:-goal32-openai-api-smoke}"
WORKER_SERVICE="${WORKER_SERVICE:-worker}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

worker_was_running="no"
snapshot_host=""
request_id=""

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'
}

cleanup() {
  if [ -n "$snapshot_host" ] && [ -f "$snapshot_host" ]; then
    rm -f "$snapshot_host"
  fi
  if [ "$worker_was_running" = "yes" ]; then
    log "Restarting long-lived worker service."
    docker compose --profile worker up -d "$WORKER_SERVICE" >/dev/null
  fi
}

require_no_summary_rows() {
  status="$1"
  rows="$(docker compose run --rm -T api request-list --status "$status" --limit 1 </dev/null)"
  if printf '%s\n' "$rows" | grep -q '"id"'; then
    fail "existing $status request found; clear or finish active queue work before openai-api smoke"
  fi
}

extract_json_string() {
  key="$1"
  sed -n "s/.*\"$key\": \"\([^\"]*\)\".*/\1/p" | head -n 1
}

[ -d "$APP_ROOT" ] || fail "APP_ROOT does not exist: $APP_ROOT"
[ -f "$ENV_FILE" ] || fail "env file does not exist: $ENV_FILE"
cd "$APP_ROOT"

env_perm="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
if [ "$env_perm" != "600" ]; then
  fail "$ENV_FILE permission must be 600, current=${env_perm:-unknown}"
fi

persistent_enabled="$(env_value OPENAI_API_RUNNER_ENABLED | tr '[:upper:]' '[:lower:]')"
case "$persistent_enabled" in
  ""|0|false|no|off) ;;
  *) fail "keep OPENAI_API_RUNNER_ENABLED disabled in .env; this script enables it only for the one-shot worker" ;;
esac

model="$(env_value OPENAI_API_MODEL)"
[ -n "$model" ] || fail "OPENAI_API_MODEL must be set in $ENV_FILE"
admin_token="$(env_value APP_ADMIN_TOKEN)"
if [ -z "$admin_token" ]; then
  admin_token="$(env_value APP_API_TOKEN)"
fi
[ -n "$admin_token" ] || fail "APP_ADMIN_TOKEN or APP_API_TOKEN must be set in $ENV_FILE"

key_value="$(env_value OPENAI_API_KEY)"
key_file="$(env_value OPENAI_API_KEY_FILE)"
if [ -z "$key_value" ] && [ -z "$key_file" ]; then
  fail "OPENAI_API_KEY or OPENAI_API_KEY_FILE must be set in $ENV_FILE"
fi
if [ -z "$key_value" ] && [ -n "$key_file" ]; then
  docker compose run --rm -T --entrypoint sh api \
    -c '[ -n "$OPENAI_API_KEY_FILE" ] && [ -s "$OPENAI_API_KEY_FILE" ]' \
    >/dev/null || fail "OPENAI_API_KEY_FILE is set but not readable inside the api container"
fi

docker compose exec -T api curl -fsS "$API_HEALTH_URL" >/dev/null

if docker compose --profile worker ps --status running --services 2>/dev/null | grep -qx "$WORKER_SERVICE"; then
  worker_was_running="yes"
  log "Stopping long-lived worker service for isolated openai-api one-shot."
  docker compose --profile worker stop "$WORKER_SERVICE" >/dev/null
fi
trap cleanup EXIT INT TERM

require_no_summary_rows queued
require_no_summary_rows running

umask 077
mkdir -p "$BACKUP_DIR"
snapshot_host="$(mktemp "$BACKUP_DIR/openai-api-smoke.XXXXXX.md")"
snapshot_container="/backups/$(basename "$snapshot_host")"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat >"$snapshot_host" <<EOF
---
title: OpenAI API 러너 스모크 $STAMP
type: capture
status: inbox
created: $created_at
source: $SMOKE_SOURCE
---

# OpenAI API 러너 스모크 $STAMP

이 제어된 스모크 요청은 OpenAI API 러너의 실사용 동작을 확인합니다.

## 근거

- 검증 대상 러너: openai-api.
- 기대 결과: wiki/sources/ 아래에 소스 노트가 정확히 1개 생성됩니다.
- 운영 기본 fallback은 codex-cli이며 API 러너는 기본 비활성 상태입니다.
- 주제와 대상 후보는 검토 가능한 제안으로만 남아야 합니다.
EOF

note_json="$(
  docker compose run --rm -T api note-create \
    --title "OpenAI API 러너 스모크 $STAMP" \
    --kind inbox \
    --status active \
    --body-file "$snapshot_container" \
    --metadata-json "{\"source\":\"$SMOKE_SOURCE\"}" \
    --change-source smoke \
    --created-by smoke \
    </dev/null
)"
note_id="$(printf '%s\n' "$note_json" | extract_json_string id)"
note_version="$(printf '%s\n' "$note_json" | sed -n 's/.*"version": \([0-9][0-9]*\).*/\1/p' | head -n 1)"
[ -n "$note_id" ] || fail "could not parse created note id"
[ -n "$note_version" ] || fail "could not parse created note version"

request_json="$(
  docker compose exec -T api curl -fsS \
    -X POST "$API_BASE_URL/api/notes/$note_id/process" \
    -H "Authorization: Bearer $admin_token" \
    -H "Content-Type: application/json" \
    -d "{\"expected_version\":$note_version,\"sensitivity\":\"internal\"}"
)"
request_id="$(printf '%s\n' "$request_json" | extract_json_string id)"
[ -n "$request_id" ] || fail "could not parse created request id"
log "Created smoke request: $request_id"

worker_json="$(
  docker compose run --rm -T -e OPENAI_API_RUNNER_ENABLED=true api worker --runner openai-api </dev/null
)"
log "$worker_json"

summary_json="$(
  docker compose run --rm -T api request-list --query "$request_id" --limit 1 </dev/null
)"
status="$(printf '%s\n' "$summary_json" | extract_json_string status)"
[ -n "$status" ] || fail "could not parse smoke request status"

case "$status" in
  succeeded)
    log "OpenAI API smoke succeeded."
    log "Request: $request_id"
    ;;
  queued|running|needs_sync)
    docker compose run --rm -T api request-cancel "$request_id" \
      --reason "goal32 openai-api smoke cleanup after status $status" \
      >/dev/null || true
    fail "openai-api smoke did not complete; request was $status and was cancelled if possible"
    ;;
  *)
    fail "openai-api smoke did not succeed; request status=$status, request=$request_id"
    ;;
esac

rollback_status="$(
  docker compose run --rm -T api worker-status </dev/null
)"
rollback_runner="$(printf '%s\n' "$rollback_status" | extract_json_string worker_runner)"
rollback_enabled="$(printf '%s\n' "$rollback_status" | sed -n 's/.*"openai_api_runner_enabled": \(true\|false\).*/\1/p' | head -n 1)"
if [ "$rollback_runner" != "codex-cli" ]; then
  fail "rollback check expected worker_runner=codex-cli, got ${rollback_runner:-unknown}"
fi
if [ "$rollback_enabled" != "false" ]; then
  fail "rollback check expected openai_api_runner_enabled=false, got ${rollback_enabled:-unknown}"
fi
log "Rollback baseline verified: worker_runner=codex-cli, openai_api_runner_enabled=false."
