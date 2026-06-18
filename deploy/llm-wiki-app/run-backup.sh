#!/bin/sh
set -eu

RETENTION_DAYS="${RETENTION_DAYS:-30}"
APP_ROOT="${APP_ROOT:-$HOME/services/llm-wiki-app}"
RESTORE_SMOKE_ENABLED="${RESTORE_SMOKE_ENABLED:-true}"
RESTORE_SMOKE_DB_PASSWORD="${RESTORE_SMOKE_DB_PASSWORD:-llm-wiki-restore-smoke}"
REPO_BUNDLE_BACKUP_ENABLED="${REPO_BUNDLE_BACKUP_ENABLED:-false}"
export RESTORE_SMOKE_DB_PASSWORD

cd "$APP_ROOT"
mkdir -p "$APP_ROOT/backups"
chmod 700 "$APP_ROOT/backups"

cleanup_restore_smoke() {
  if [ "$RESTORE_SMOKE_ENABLED" = "true" ]; then
    docker compose --profile restore-smoke rm -sf restore-smoke-db >/dev/null 2>&1 || true
  fi
}

set -- \
  --target /backups \
  --postgres \
  --object-manifest \
  --verify-objects \
  --object-data \
  --retention-days "$RETENTION_DAYS"

if [ "$REPO_BUNDLE_BACKUP_ENABLED" = "true" ]; then
  set -- "$@" --repo-bundle --repo-restore-smoke
fi

if [ "$RESTORE_SMOKE_ENABLED" = "true" ]; then
  cleanup_restore_smoke
  docker compose --profile restore-smoke up -d restore-smoke-db
  trap cleanup_restore_smoke EXIT INT TERM
  set -- "$@" \
    --restore-smoke \
    --db-restore-url "postgresql://llm_wiki_restore:${RESTORE_SMOKE_DB_PASSWORD}@restore-smoke-db:5432/llm_wiki_restore" \
    --mirror-restore-target /tmp/restore-smoke-mirror \
    --object-restore-target /tmp/restore-smoke-objects
fi

backup_result="$APP_ROOT/backups/llm-wiki-backup-run-$(date -u +%Y%m%dT%H%M%SZ).json"
if docker compose run --rm -T api backup "$@" > "$backup_result.tmp" </dev/null; then
  mv "$backup_result.tmp" "$backup_result"
  chmod 600 "$backup_result"
  cat "$backup_result"
else
  status=$?
  cat "$backup_result.tmp" >&2 || true
  rm -f "$backup_result.tmp"
  exit "$status"
fi
