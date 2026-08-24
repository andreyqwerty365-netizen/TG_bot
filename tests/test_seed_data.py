from __future__ import annotations

import base64
import gzip
import sqlite3
from pathlib import Path

from bot.services.seed_data import restore_seed_databases


def _sqlite_payload(tmp_path: Path, *, compressed: bool = False) -> str:
    raw_path = tmp_path / "seed-source.sqlite3"
    connection = sqlite3.connect(raw_path)
    try:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES ('original')")
        connection.commit()
        connection.close()
        raw = raw_path.read_bytes()
        if compressed:
            raw = gzip.compress(raw)
        return base64.b64encode(raw).decode("ascii")
    finally:
        connection.close()
        raw_path.unlink(missing_ok=True)


def test_restore_seed_databases_writes_valid_sqlite_and_marker(tmp_path: Path) -> None:
    target = tmp_path / "notes.db"
    marker = tmp_path / ".initial-seed-v1"

    restored = restore_seed_databases({target: _sqlite_payload(tmp_path)}, marker)

    assert restored == [target]
    assert marker.exists()
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("original",)


def test_restore_seed_databases_does_not_overwrite_after_marker(tmp_path: Path) -> None:
    target = tmp_path / "notes.db"
    marker = tmp_path / ".initial-seed-v1"
    target.write_bytes(b"current data")
    marker.write_text("done", encoding="utf-8")

    restored = restore_seed_databases({target: _sqlite_payload(tmp_path)}, marker)

    assert restored == []
    assert target.read_bytes() == b"current data"


def test_restore_seed_databases_accepts_gzip_payload(tmp_path: Path) -> None:
    target = tmp_path / "notes.db"

    restored = restore_seed_databases(
        {target: _sqlite_payload(tmp_path, compressed=True)},
        tmp_path / ".initial-seed-v1",
    )

    assert restored == [target]
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("original",)
