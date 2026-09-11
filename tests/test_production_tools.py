from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bot.db import Database
from tools.healthcheck import check_database as check_healthy_database
from tools.production_preflight import check_compose, check_database
from tools import sqlite_online_backup

ROOT = Path(__file__).resolve().parents[1]


def test_production_preflight_accepts_database_and_compose(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "\n".join(
            [
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
            ]
        ),
        encoding="utf-8",
    )

    check_database(db.db_path)
    check_compose(compose)


def test_production_preflight_rejects_incomplete_compose(tmp_path: Path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services:\n  bot:\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="incomplete"):
        check_compose(compose)


def test_healthcheck_accepts_initialized_database(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()

    check_healthy_database(db.db_path)


def test_healthcheck_rejects_database_without_schema(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    with pytest.raises(SystemExit, match="schema is incomplete"):
        check_healthy_database(db_path)


def test_vps_preflight_checks_dependencies_and_secret_files():
    text = (ROOT / "deploy" / "preflight.sh").read_text(encoding="utf-8")

    for required in [
        "require_command docker",
        "require_command restic",
        "require_command python3",
        "require_command stat",
        "require_bot_owned_directory",
        '"10001"',
        "RESTIC_REPOSITORY",
        "AWS_SECRET_ACCESS_KEY",
        "BOT_ALERT_CHAT_ID",
        "docker compose",
        "tools/healthcheck.py",
    ]:
        assert required in text
    assert 'require_env_value "$APP_ENV_FILE" BOT_ALLOWED_USER_IDS' not in text


def test_health_monitor_keeps_host_state_outside_container_data():
    text = (ROOT / "deploy" / "check_bot_health.sh").read_text(encoding="utf-8")

    assert 'STATE_FILE="${STATE_FILE:-$ROOT_DIR/.monitor.status}"' in text
    assert "$ROOT_DIR/data/monitor.status" not in text


def test_sqlite_online_backup_creates_checked_snapshot(tmp_path: Path):
    db = Database(tmp_path / "notes.db")
    db.init()
    db.add_note(1, "Проверка backup")
    snapshot = tmp_path / "backups" / "notes-latest.db"

    sqlite_online_backup.create_backup(db.db_path, snapshot)

    check_healthy_database(snapshot)
    restored = Database(snapshot)
    assert restored.count_notes(1) == 1


def test_sqlite_online_backup_keeps_previous_snapshot_when_validation_fails(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "notes.db")
    db.init()
    snapshot = tmp_path / "notes-latest.db"
    previous_content = b"previous verified snapshot"
    snapshot.write_bytes(previous_content)

    def reject_snapshot(_: Path) -> None:
        raise sqlite3.DatabaseError("simulated verification failure")

    monkeypatch.setattr(sqlite_online_backup, "verify_backup", reject_snapshot)
    with pytest.raises(sqlite3.DatabaseError, match="simulated"):
        sqlite_online_backup.create_backup(db.db_path, snapshot)

    assert snapshot.read_bytes() == previous_content
    assert not list(tmp_path.glob(".notes-latest.db.*.tmp"))
