from __future__ import annotations

import argparse
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path


REQUIRED_TABLES = {"notes", "reminders", "chat_settings"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a consistent SQLite backup while the bot is running.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    return parser.parse_args()


def verify_backup(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path, timeout=5)) as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('notes', 'reminders', 'chat_settings')"
            )
        }
    if result != ("ok",):
        raise sqlite3.DatabaseError(f"SQLite backup integrity check failed: {result}")
    missing = REQUIRED_TABLES - tables
    if missing:
        raise sqlite3.DatabaseError(f"SQLite backup schema is incomplete: missing {', '.join(sorted(missing))}")


def create_backup(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")
    if source == destination:
        raise ValueError("Source and destination must be different files.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(source, timeout=30)) as source_conn:
            with closing(sqlite3.connect(temporary)) as destination_conn:
                source_conn.backup(destination_conn)
        verify_backup(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    destination = args.destination.expanduser().resolve()
    try:
        create_backup(args.source, destination)
    except (FileNotFoundError, ValueError, sqlite3.DatabaseError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"SQLite backup created: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
