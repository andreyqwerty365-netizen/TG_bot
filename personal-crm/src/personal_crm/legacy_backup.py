"""Encrypted online snapshots of the two legacy SQLite databases, without polling."""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .recovery import MAX_BYTES, RecoveryError, _read, _write, ledger_lock, seal, unseal
from .remote_backup import S3Config, S3Store, validate

FILES = ("notes.db", "workouts.sqlite3")
PURPOSE = "legacy-sqlite-v1"
NAME = re.compile(r"legacy-\d{8}T\d{6}Z-[a-f0-9]{12}\.botb\Z")
DB_LIMIT = 20 * 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError()
    return result


def _connection(path, *, snapshot=False):
    # immutable is safe only for our closed standalone snapshots, never the live WAL source.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro" + ("&immutable=1" if snapshot else ""), uri=True, timeout=5)
    db.execute("PRAGMA query_only=ON")
    deadline = time.monotonic() + 90
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    return db


def _inspect(path):
    if not 0 < path.stat().st_size <= DB_LIMIT:
        raise RecoveryError("database_size_limit")
    with closing(_connection(path, snapshot=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RecoveryError("database_integrity_failed")
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            hashes = []
            for row in db.execute("SELECT * FROM " + quoted):
                # Include type and bytes; sorting row digests preserves duplicates without depending on row order.
                values = [(type(v).__name__, v.hex() if isinstance(v, (bytes, float)) else v) for v in row]
                hashes.append(hashlib.sha256(_json(values)).digest())
            tables[name] = {"rows": len(hashes), "sha256": hashlib.sha256(b"".join(sorted(hashes))).hexdigest()}
        if not tables:
            raise RecoveryError("database_empty_schema")
        return {"schema_sha256": hashlib.sha256(_json(schema)).hexdigest(), "tables": tables}


def create_archive(source, key, *, now=None):
    now = now or datetime.now(UTC)
    _stamp(now.isoformat())
    source = Path(source)
    document = {"version": 1, "kind": PURPOSE, "created_at": now.isoformat(), "databases": {}}
    try:
        with tempfile.TemporaryDirectory(prefix="legacy-snapshot-") as scratch:
            for name in FILES:
                path = source / name
                if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= DB_LIMIT:
                    raise RecoveryError("source_invalid")
                snapshot = Path(scratch) / name
                # Backup API includes committed WAL pages and does not checkpoint or mutate the source.
                with closing(_connection(path)) as live, closing(sqlite3.connect(snapshot)) as target:
                    deadline = time.monotonic() + 90
                    page_size = live.execute("PRAGMA page_size").fetchone()[0]

                    def progress(status, remaining, total):
                        if time.monotonic() > deadline or total * page_size > DB_LIMIT:
                            raise RecoveryError("snapshot_limit")

                    live.backup(target, pages=128, progress=progress, sleep=0.05)
                info = _inspect(snapshot)
                raw = snapshot.read_bytes()
                document["databases"][name] = {**info, "sha256": hashlib.sha256(raw).hexdigest(),
                                               "data": base64.b64encode(raw).decode("ascii")}
        value = seal(_json(document), key, PURPOSE)
        if len(value) > MAX_BYTES:
            raise RecoveryError("archive_too_large")
        return value
    except (OSError, sqlite3.Error):
        raise RecoveryError("snapshot_failed") from None


def _decode(value, key):
    try:
        document = json.loads(unseal(value, key, PURPOSE))
        if (document["version"] != 1 or document["kind"] != PURPOSE
                or set(document["databases"]) != set(FILES)):
            raise ValueError()
        _stamp(document["created_at"])
        raw = {}
        for name, info in document["databases"].items():
            data = base64.b64decode(info["data"], validate=True)
            if not 0 < len(data) <= DB_LIMIT or hashlib.sha256(data).hexdigest() != info["sha256"]:
                raise ValueError()
            raw[name] = data
        return document, raw
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RecoveryError("archive_invalid") from None


def restore_archive(value, key, target):
    document, raw = _decode(value, key)
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise RecoveryError("restore_target_exists")
    created = False
    try:
        target.mkdir(mode=0o700)  # Refuse races and require an existing trusted parent.
        created = True
        databases = {}
        for name in FILES:
            _write(target / name, raw[name])
            info = _inspect(target / name)
            expected = document["databases"][name]
            if info != {k: expected[k] for k in ("schema_sha256", "tables")}:
                raise RecoveryError("restore_verification_failed")
            databases[name] = info
        return {"status": "restored_verified", "created_at": document["created_at"], "databases": databases}
    except (OSError, sqlite3.Error, KeyError):
        raise RecoveryError("restore_failed") from None
    finally:
        # A failed restore is never left looking like a complete usable pair.
        if created and len(locals().get("databases", {})) != len(FILES):
            shutil.rmtree(target)


def _call(store, method, *args):
    try:
        return getattr(store, method)(*args)
    except RecoveryError:
        raise
    except Exception:
        raise RecoveryError("remote_storage_failed") from None


def run_backup(source, directory, key, remote, *, store=None, now=None):
    validate(remote)
    store = store or S3Store(remote)
    now = now or datetime.now(UTC)
    _stamp(now.isoformat())
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with ledger_lock(directory / ".job"):
        value = create_archive(source, key, now=now)
        name = "legacy-" + now.strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12] + ".botb"
        local = directory / name
        _write(local, value)
        object_key = remote.prefix + "/archives/" + name
        _call(store, "put", object_key, value)
        downloaded = _call(store, "get", object_key)
        if downloaded != value:
            raise RecoveryError("remote_verification_failed")
        with tempfile.TemporaryDirectory(prefix="legacy-verify-") as scratch:
            report = restore_archive(downloaded, key, Path(scratch) / "restored")
        head = seal(_json({"version": 1, "object": object_key, "sha256": hashlib.sha256(value).hexdigest()}), key, PURPOSE + "-head")
        _call(store, "put", remote.prefix + "/latest.botb", head)
        if _call(store, "get", remote.prefix + "/latest.botb") != head:
            raise RecoveryError("remote_verification_failed")
        # Never prune foreign, unreadable, future-dated or currently published archives.
        cutoff = now - timedelta(days=30)
        for candidate in _call(store, "keys", remote.prefix + "/archives/"):
            old_name = candidate.removeprefix(remote.prefix + "/archives/")
            if not NAME.fullmatch(old_name) or candidate == object_key:
                continue
            try:
                old, _ = _decode(_call(store, "get", candidate), key)
            except (RecoveryError, TypeError):
                continue
            if _stamp(old["created_at"]) < cutoff:
                _call(store, "delete", candidate)
        for old_path in directory.glob("*.botb"):
            if not NAME.fullmatch(old_path.name) or old_path == local or old_path.is_symlink():
                continue
            try:
                old, _ = _decode(_read(old_path, "archive_read_failed"), key)
            except RecoveryError:
                continue
            if _stamp(old["created_at"]) < cutoff:
                old_path.unlink()
        result = {**report, "status": "verified_remote", "object": object_key}
        _write(directory / "last-success.json", _json(result), replace=True)
        return result


def download_restore(remote, key, target, *, store=None, object_key=None):
    validate(remote)
    store = store or S3Store(remote)
    digest = None
    if object_key is None:
        try:
            head = json.loads(unseal(_call(store, "get", remote.prefix + "/latest.botb") or b"", key, PURPOSE + "-head"))
            if head["version"] != 1:
                raise ValueError()
            object_key, digest = head["object"], head["sha256"]
        except (ValueError, KeyError, TypeError):
            raise RecoveryError("remote_head_invalid") from None
    root = remote.prefix + "/archives/"
    if not isinstance(object_key, str) or not object_key.startswith(root) or not NAME.fullmatch(object_key[len(root):]):
        raise RecoveryError("remote_object_invalid")
    value = _call(store, "get", object_key)
    if value is None or (digest and hashlib.sha256(value).hexdigest() != digest):
        raise RecoveryError("remote_verification_failed")
    result = {**restore_archive(value, key, target), "object": object_key}
    _write(Path(target) / "RESTORE_REPORT.json", _json(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("backup", "download-restore"))
    parser.add_argument("--target", type=Path)
    parser.add_argument("--object")
    args = parser.parse_args()
    try:
        if os.getenv("LEGACY_BACKUP_CONFIRMED") != "true":
            raise RecoveryError("external_backup_target_unconfirmed")
        remote = S3Config(True, os.getenv("LEGACY_S3_ENDPOINT", ""), os.getenv("LEGACY_S3_BUCKET", ""),
                          os.getenv("LEGACY_S3_ACCESS_KEY", ""), os.getenv("LEGACY_S3_SECRET_KEY", ""),
                          os.getenv("LEGACY_S3_REGION", "default"), os.getenv("LEGACY_S3_PREFIX", "legacy-bot"))
        key = Path(os.environ["LEGACY_BACKUP_KEY_FILE"]).read_text().strip()
        if args.command == "backup":
            result = run_backup(Path(os.environ["LEGACY_SOURCE_DIRECTORY"]), Path(os.environ["LEGACY_BACKUP_DIRECTORY"]), key, remote)
        else:
            if args.target is None:
                raise RecoveryError("restore_target_required")
            result = download_restore(remote, key, args.target, object_key=args.object)
        print(json.dumps(result, sort_keys=True))
    except (RecoveryError, OSError, KeyError) as error:
        code = str(error) if isinstance(error, RecoveryError) else "private_configuration_invalid"
        print(json.dumps({"status": "failed", "code": code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
