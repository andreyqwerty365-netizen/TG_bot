from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

REQUIRED_TABLES = {"notes", "reminders", "chat_settings"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check that the assistant SQLite database is readable.")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("BOT_DB_PATH", "notes.db")))
    return parser.parse_args()


def check_database(db_path: Path) -> None:
    db_path = db_path.expanduser().resolve()
    if not db_path.is_file():
        raise SystemExit(f"Database does not exist: {db_path}")
    with closing(sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, timeout=5)) as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('notes', 'reminders', 'chat_settings')"
            )
        }
    if result != ("ok",):
        raise SystemExit(f"Database healthcheck failed: {result}")
    missing = REQUIRED_TABLES - tables
    if missing:
        raise SystemExit(f"Database schema is incomplete: missing {', '.join(sorted(missing))}")


def main() -> int:
    check_database(parse_args().db)
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
