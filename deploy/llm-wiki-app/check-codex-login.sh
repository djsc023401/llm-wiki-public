#!/bin/sh
set -eu

APP_ROOT="${APP_ROOT:-$HOME/services/llm-wiki-app}"

cd "$APP_ROOT"
docker compose run --rm -T --entrypoint codex api login status </dev/null
