#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RESTIC_ENV_FILE="${RESTIC_ENV_FILE:-/etc/telegram-assistant/restic.env}"
TARGET_DIR="${1:-/tmp/telegram-assistant-restore-$(date +%Y%m%d-%H%M%S)}"

if [[ -e "$TARGET_DIR" ]]; then
  printf 'Restore target already exists: %s\n' "$TARGET_DIR" >&2
  exit 1
fi

set -a
source "$RESTIC_ENV_FILE"
set +a

mkdir -p "$TARGET_DIR"
restic restore latest --tag telegram-assistant --target "$TARGET_DIR"

RESTORED_DB="$TARGET_DIR$ROOT_DIR/data/backups/notes-latest.db"
python3 "$ROOT_DIR/tools/healthcheck.py" --db "$RESTORED_DB"
printf 'Restore verified: %s\n' "$RESTORED_DB"
