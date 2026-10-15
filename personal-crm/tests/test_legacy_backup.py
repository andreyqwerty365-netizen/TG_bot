"""Synthetic SQLite/WAL data only; no Telegram or production credentials."""
import base64
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from personal_crm.legacy_backup import create_archive, download_restore, restore_archive, run_backup
from personal_crm.recovery import RecoveryError, seal, unseal
from personal_crm.remote_backup import S3Config

KEY = base64.urlsafe_b64encode(b"s" * 32).decode()
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
REMOTE = S3Config(True, "https://s3.example.invalid", "synthetic", "access", "secret", "default", "legacy-bot")


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / "source"
    directory.mkdir()
    for name in ("notes.db", "workouts.sqlite3"):
        with closing(sqlite3.connect(directory / name)) as db:
            db.execute("CREATE TABLE entries(id INTEGER PRIMARY KEY, content TEXT, raw BLOB)")
            db.execute("INSERT INTO entries VALUES(1, 'synthetic private text', X'00FF')")
            db.commit()
    return directory


class Store:
    def __init__(self):
        self.values = {}
        self.corrupt = False
        self.fail = False
        self.deleted = []

    def put(self, key, value):
        if self.fail:
            raise RuntimeError("private-provider-detail")
        self.values[key] = value

    def get(self, key):
        value = self.values.get(key)
        return b"corrupt" if self.corrupt and value else value

    def keys(self, prefix):
        return [key for key in self.values if key.startswith(prefix)]

    def delete(self, key):
        self.deleted.append(key)
        del self.values[key]


def test_live_wal_and_both_databases_restore(source, tmp_path):
    db = sqlite3.connect(source / "notes.db")
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO entries VALUES(2, 'committed in WAL', NULL)")
        db.commit()
        value = create_archive(source, KEY, now=NOW)
        assert b"synthetic private text" not in value
        report = restore_archive(value, KEY, tmp_path / "restored")
        assert report["status"] == "restored_verified"
        assert report["databases"]["notes.db"]["tables"]["entries"]["rows"] == 2
        with closing(sqlite3.connect(tmp_path / "restored" / "notes.db")) as restored:
            assert restored.execute("SELECT content FROM entries WHERE id=2").fetchone() == ("committed in WAL",)
        assert (tmp_path / "restored" / "workouts.sqlite3").exists()
    finally:
        db.close()


@pytest.mark.parametrize("damage", ["key", "bytes", "missing", "path", "hash"])
def test_invalid_archive_never_creates_restore_directory(source, tmp_path, damage):
    value = create_archive(source, KEY, now=NOW)
    key = KEY
    if damage == "key":
        key = base64.urlsafe_b64encode(b"x" * 32).decode()
    elif damage == "bytes":
        value = value[:-1] + bytes([value[-1] ^ 1])
    else:
        document = json.loads(unseal(value, KEY, "legacy-sqlite-v1"))
        if damage == "missing":
            del document["databases"]["workouts.sqlite3"]
        elif damage == "path":
            document["databases"]["../escape.db"] = document["databases"].pop("notes.db")
        else:
            document["databases"]["notes.db"]["sha256"] = "0" * 64
        value = seal(json.dumps(document).encode(), KEY, "legacy-sqlite-v1")
    target = tmp_path / "restore"
    with pytest.raises(RecoveryError):
        restore_archive(value, key, target)
    assert not target.exists()


def test_restore_never_overwrites_existing_directory_or_follows_symlink(source, tmp_path):
    value = create_archive(source, KEY, now=NOW)
    with pytest.raises(RecoveryError, match="restore_target_exists"):
        restore_archive(value, KEY, source)
    target = tmp_path / "link"
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(RecoveryError, match="restore_target_exists"):
        restore_archive(value, KEY, target)


def test_missing_source_fails_closed(source):
    (source / "workouts.sqlite3").unlink()
    with pytest.raises(RecoveryError, match="source_invalid"):
        create_archive(source, KEY, now=NOW)
    assert not (source / "workouts.sqlite3").exists()


def test_verified_remote_round_trip_and_retention_scope(source, tmp_path):
    store = Store()
    directory = tmp_path / "encrypted"
    old = run_backup(source, directory, KEY, REMOTE, store=store, now=NOW - timedelta(days=31))
    foreign = REMOTE.prefix + "/archives/foreign.botb"
    store.values[foreign] = b"other application"
    result = run_backup(source, directory, KEY, REMOTE, store=store, now=NOW)
    assert result["status"] == "verified_remote"
    assert old["object"] in store.deleted
    assert foreign in store.values
    restore_archive(store.get(result["object"]), KEY, tmp_path / "downloaded")
    assert all(b"synthetic private text" not in p.read_bytes() for p in directory.glob("*.botb"))
    assert not (directory / old["object"].rsplit("/", 1)[1]).exists()


@pytest.mark.parametrize("failure", ["corrupt", "fail"])
def test_failed_upload_does_not_prune_or_replace_verified_head(source, tmp_path, failure):
    store = Store()
    directory = tmp_path / "encrypted"
    first = run_backup(source, directory, KEY, REMOTE, store=store, now=NOW - timedelta(days=31))
    head = store.values[REMOTE.prefix + "/latest.botb"]
    setattr(store, failure, True)
    with pytest.raises(RecoveryError) as error:
        run_backup(source, directory, KEY, REMOTE, store=store, now=NOW)
    assert "private-provider-detail" not in str(error.value)
    assert not store.deleted
    assert store.values[REMOTE.prefix + "/latest.botb"] == head
    assert first["object"] in store.values


def test_concurrent_job_is_rejected(source, tmp_path):
    directory = tmp_path / "encrypted"
    directory.mkdir()
    (directory / ".job.lock").touch()
    with pytest.raises(RecoveryError, match="ledger_busy"):
        run_backup(source, directory, KEY, REMOTE, store=Store(), now=NOW)


def test_download_latest_and_detect_remote_damage(source, tmp_path):
    store = Store()
    run_backup(source, tmp_path / "encrypted", KEY, REMOTE, store=store, now=NOW)
    result = download_restore(REMOTE, KEY, tmp_path / "downloaded", store=store)
    assert result["status"] == "restored_verified"
    assert (tmp_path / "downloaded" / "RESTORE_REPORT.json").exists()
    store.corrupt = True
    with pytest.raises(RecoveryError):
        download_restore(REMOTE, KEY, tmp_path / "damaged", store=store)
    assert not (tmp_path / "damaged").exists()


def test_authenticated_but_invalid_sqlite_leaves_no_partial_restore(source, tmp_path):
    value = create_archive(source, KEY, now=NOW)
    document = json.loads(unseal(value, KEY, "legacy-sqlite-v1"))
    import hashlib
    invalid = b"not a sqlite database"
    document["databases"]["workouts.sqlite3"].update(data=base64.b64encode(invalid).decode(),
                                                    sha256=hashlib.sha256(invalid).hexdigest())
    value = seal(json.dumps(document).encode(), KEY, "legacy-sqlite-v1")
    with pytest.raises(RecoveryError):
        restore_archive(value, KEY, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_cli_requires_explicit_backup_confirmation(tmp_path):
    import os
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-m", "personal_crm.legacy_backup", "backup"],
                            env={**os.environ, "LEGACY_BACKUP_CONFIRMED": "false"},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"status": "failed", "code": "external_backup_target_unconfirmed"}
    assert not result.stderr


def test_host_wrapper_holds_only_readonly_connections_and_propagates_failure(source, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    path = Path(__file__).parents[1] / "deploy" / "legacy_backup_job.py"
    spec = importlib.util.spec_from_file_location("legacy_backup_job", path)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    real_connect = sqlite3.connect
    opened = []

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    def job(*args, **kwargs):
        assert len(opened) == 2
        for db in opened:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                db.execute("INSERT INTO entries VALUES(2, 'forbidden', NULL)")
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(wrapper.sqlite3, "connect", connect)
    monkeypatch.setattr(wrapper.subprocess, "run", job)
    monkeypatch.setattr(sys, "argv", [str(path), "--source", str(source)])
    assert wrapper.main() == 7
    for db in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            db.execute("SELECT 1")
