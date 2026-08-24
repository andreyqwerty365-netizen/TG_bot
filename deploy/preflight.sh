#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ENV_FILE="${APP_ENV_FILE:-$ROOT_DIR/.env.vps}"
RESTIC_ENV_FILE="${RESTIC_ENV_FILE:-/etc/telegram-assistant/restic.env}"
ALERT_ENV_FILE="${ALERT_ENV_FILE:-/etc/telegram-assistant/alert.env}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

require_file() {
  if [[ ! -f "$1" ]]; then
    printf 'Missing required file: %s\n' "$1" >&2
    exit 1
  fi
}

require_bot_owned_directory() {
  local directory="$1"
  if [[ ! -d "$directory" ]]; then
    printf 'Missing required data directory: %s\n' "$directory" >&2
    exit 1
  fi
  if [[ "$(stat -c '%u' "$directory")" != "10001" ]]; then
    printf 'Data directory must be owned by container UID 10001: %s\n' "$directory" >&2
    exit 1
  fi
}

require_env_value() {
  local file="$1"
  local key="$2"
  local value
  value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$file")"
  if [[ -z "$value" || "$value" == replace_* || "$value" == your_* || "$value" == *example.com* ]]; then
    printf 'Missing configured value: %s in %s\n' "$key" "$file" >&2
    exit 1
  fi
}

require_command docker
require_command restic
require_command python3
require_command stat
require_file "$APP_ENV_FILE"
require_file "$RESTIC_ENV_FILE"
require_file "$ALERT_ENV_FILE"

require_env_value "$APP_ENV_FILE" BOT_TOKEN
require_env_value "$APP_ENV_FILE" BOT_ALLOWED_USER_IDS
require_env_value "$RESTIC_ENV_FILE" RESTIC_REPOSITORY
require_env_value "$RESTIC_ENV_FILE" RESTIC_PASSWORD
require_env_value "$RESTIC_ENV_FILE" AWS_ACCESS_KEY_ID
require_env_value "$RESTIC_ENV_FILE" AWS_SECRET_ACCESS_KEY
require_env_value "$ALERT_ENV_FILE" BOT_TOKEN
require_env_value "$ALERT_ENV_FILE" BOT_ALERT_CHAT_ID

docker compose -f "$ROOT_DIR/docker-compose.yml" config >/dev/null
require_bot_owned_directory "$ROOT_DIR/data"
require_bot_owned_directory "$ROOT_DIR/data/logs"
require_bot_owned_directory "$ROOT_DIR/data/backups"

if [[ -f "$ROOT_DIR/data/notes.db" ]]; then
  python3 "$ROOT_DIR/tools/healthcheck.py" --db "$ROOT_DIR/data/notes.db"
else
  printf 'Database does not exist yet; first container start will create it.\n'
fi

printf 'VPS preflight passed.\n'
