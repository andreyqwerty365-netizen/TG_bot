from __future__ import annotations

import argparse
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path


REQUIRED_COMPOSE_SNIPPETS = (
    "restart: unless-stopped",
    "BOT_DB_PATH: /data/notes.db",
    "BOT_LOG_PATH: /data/logs/bot.log",
    "BOT_INTERACTION_LOG_PATH: /data/logs/interactions.log",
    "./data:/data",
    "read_only: true",
    "no-new-privileges:true",
    "cap_drop:",
    "- ALL",
    "tmpfs:",
    "- /tmp",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate local data and VPS deployment files before rollout.")
    parser.add_argument("--db", type=Path, default=Path("notes.db"))
    parser.add_argument("--compose", type=Path, default=Path("docker-compose.yml"))
    return parser.parse_args()


def check_database(db_path: Path) -> None:
    source = db_path.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Database does not exist: {source}")
    snapshot = source.with_name(f".{source.name}.preflight-{uuid.uuid4().hex}.db")
    try:
        with closing(sqlite3.connect(source, timeout=30)) as source_conn:
            with closing(sqlite3.connect(snapshot)) as snapshot_conn:
                source_conn.backup(snapshot_conn)
        with closing(sqlite3.connect(snapshot, timeout=5)) as snapshot_conn:
            result = snapshot_conn.execute("PRAGMA integrity_check").fetchone()
            tables = {
                row[0]
                for row in snapshot_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('notes', 'reminders', 'chat_settings')"
                )
            }
    finally:
        snapshot.unlink(missing_ok=True)
    if result != ("ok",):
        raise SystemExit(f"SQLite integrity check failed: {result}")
    missing = {"notes", "reminders", "chat_settings"} - tables
    if missing:
        raise SystemExit(f"SQLite schema is incomplete: missing {', '.join(sorted(missing))}")


def check_compose(compose_path: Path) -> None:
    compose = compose_path.expanduser().resolve()
    if not compose.is_file():
        raise SystemExit(f"Docker Compose file does not exist: {compose}")
    text = compose.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_COMPOSE_SNIPPETS if snippet not in text]
    if missing:
        raise SystemExit("Docker Compose config is incomplete: " + ", ".join(missing))


def main() -> int:
    args = parse_args()
    check_database(args.db)
    check_compose(args.compose)
    print("Production preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
