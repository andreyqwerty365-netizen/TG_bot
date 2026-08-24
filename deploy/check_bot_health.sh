#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ALERT_ENV_FILE="${ALERT_ENV_FILE:-/etc/telegram-assistant/alert.env}"
STATE_FILE="${STATE_FILE:-$ROOT_DIR/.monitor.status}"
CONTAINER_NAME="${BOT_CONTAINER_NAME:-telegram-assistant-bot}"

mkdir -p "$(dirname -- "$STATE_FILE")"
current="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER_NAME" 2>/dev/null || printf 'missing unknown')"
previous="$(cat "$STATE_FILE" 2>/dev/null || true)"

if [[ "$current" != "$previous" && -f "$ALERT_ENV_FILE" ]]; then
  set -a
  source "$ALERT_ENV_FILE"
  set +a
  python3 "$ROOT_DIR/tools/send_telegram_alert.py" "Telegram assistant state on $(hostname): $current" || true
fi

printf '%s\n' "$current" > "$STATE_FILE"
[[ "$current" == "running healthy" ]]
