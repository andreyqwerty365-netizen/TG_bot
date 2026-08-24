#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RESTIC_ENV_FILE="${RESTIC_ENV_FILE:-/etc/telegram-assistant/restic.env}"
ALERT_ENV_FILE="${ALERT_ENV_FILE:-/etc/telegram-assistant/alert.env}"

notify_failure() {
  local status=$?
  if [[ -f "$ALERT_ENV_FILE" ]]; then
    set -a
    source "$ALERT_ENV_FILE"
    set +a
    python3 "$ROOT_DIR/tools/send_telegram_alert.py" "Telegram assistant backup failed on $(hostname)." || true
  fi
  exit "$status"
}
trap notify_failure ERR

set -a
source "$RESTIC_ENV_FILE"
set +a

mkdir -p "$ROOT_DIR/data/backups"
docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T bot \
  python tools/sqlite_online_backup.py \
  --source /data/notes.db \
  --destination /data/backups/notes-latest.db

restic backup "$ROOT_DIR/data/backups/notes-latest.db" --tag telegram-assistant
restic forget --tag telegram-assistant --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
