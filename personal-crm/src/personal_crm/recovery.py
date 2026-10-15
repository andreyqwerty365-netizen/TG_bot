"""Encrypted PostgreSQL backups and isolated restore rehearsals."""
import base64
import binascii
import hashlib
import json
import os
import re
import struct
import subprocess
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass, field
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg import sql
from sqlalchemy import make_url, text
from sqlalchemy import select

from .db import sessions
from .models import Base

MAGIC = b"CRM-AES256-GCM-v1\0"
MAX_BYTES = 64 * 1024 * 1024
SCHEMA = "ec82f6d410aa"
TABLES = tuple(t.name for t in Base.metadata.sorted_tables)
ARCHIVE_NAME = re.compile(r"crm-\d{8}T\d{6}Z-[a-f0-9]{12}\.crmb\Z")


class RecoveryError(Exception):
    """Only a non-sensitive code may leave this boundary."""


def _key(value):
    try:
        result = base64.b64decode(value, altchars=b"-_", validate=True)
        if len(result) != 32:
            raise ValueError()
        return result
    except (ValueError, TypeError, binascii.Error):
        raise RecoveryError("key_invalid") from None


def seal(data, key, purpose):
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(_key(key)).encrypt(nonce, data, MAGIC + purpose.encode("ascii"))


def unseal(data, key, purpose):
    aes = AESGCM(_key(key))
    try:
        if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 28 or len(data) > MAX_BYTES:
            raise ValueError()
        offset = len(MAGIC)
        return aes.decrypt(data[offset:offset + 12], data[offset + 12:], MAGIC + purpose.encode("ascii"))
    except (ValueError, InvalidTag):
        raise RecoveryError("archive_authentication_failed") from None


def _read(path, code):
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise RecoveryError("archive_too_large")
        return data
    except OSError:
        raise RecoveryError(code) from None


def _write(path, data, *, replace=False):
    """No plaintext temporary files; fsync before the atomic name change."""
    path = Path(path)
    temp = path.with_name("." + uuid4().hex + ".partial")
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temp, path)
        else:
            # A hard link publishes a fully written file without overwriting anything.
            os.link(temp, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except OSError:
        raise RecoveryError("archive_write_failed") from None
    finally:
        temp.unlink(missing_ok=True)


def initialize_ledger(path, key):
    _write(path, seal(b'{"version":1,"erased":[]}', key, "ledger"))


def read_ledger(path, key):
    try:
        value = json.loads(unseal(_read(path, "ledger_unavailable"), key, "ledger"))
        if value["version"] != 1 or not isinstance(value["erased"], list):
            raise ValueError()
        if any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in value["erased"]):
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise RecoveryError("ledger_invalid") from None


def owner_hash(owner):
    return hashlib.sha256(owner.encode("utf-8")).hexdigest()


@contextmanager
def ledger_lock(path):
    """Fail closed on concurrent maintenance; a crash leaves a visible operator lock."""
    lock = Path(str(path) + ".lock")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RecoveryError("ledger_busy") from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def database_scope(url):
    value = make_url(url)
    return hashlib.sha256(json.dumps([value.host, value.port or 5432, value.database]).encode()).hexdigest()


def _pg_env(url):
    value = make_url(url)
    if value.drivername != "postgresql+psycopg" or not value.host or not value.database:
        raise RecoveryError("postgresql_url_required")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST=value.host, PGPORT=str(value.port or 5432), PGDATABASE=value.database,
               PGUSER=value.username or "", PGPASSWORD=value.password or "", PGCONNECT_TIMEOUT="10",
               PGCLIENTENCODING="UTF8", PGAPPNAME="personal-crm-recovery")
    for name in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
        if name in value.query:
            env["PG" + name.upper()] = value.query[name]
    return env


def _run(pg_bin, name, args, url=None, data=None):
    executable = Path(pg_bin) / (name + (".exe" if os.name == "nt" else ""))
    try:
        result = subprocess.run([str(executable), *args], input=data, capture_output=True, timeout=120,
                                env=_pg_env(url) if url else os.environ.copy())
    except (OSError, subprocess.TimeoutExpired):
        raise RecoveryError("postgresql_tool_unavailable") from None
    if result.returncode:
        # stderr may contain private data, credentials or SQL: never surface it.
        raise RecoveryError("postgresql_tool_failed")
    if len(result.stdout) > MAX_BYTES:
        raise RecoveryError("archive_too_large")
    return result.stdout


def _unpack(path, key):
    return decode_archive(_read(path,'archive_unavailable'),key)


def decode_archive(encrypted,key):
    data = unseal(encrypted,key,'backup')
    try:
        size = struct.unpack("!I", data[:4])[0]
        if size > 1024 * 1024:
            raise ValueError()
        manifest = json.loads(data[4:4 + size])
        dump = data[4 + size:]
        if manifest["version"] != 1 or manifest["schema_revision"] not in (SCHEMA,'db71ea6c903f','ca294b816edf'):
            raise ValueError()
        expected_tables=set(TABLES)
        if manifest['schema_revision']=='ca294b816edf':
            expected_tables-= {'web_sessions','login_throttles','worker_status'}
        elif manifest['schema_revision']=='db71ea6c903f':
            expected_tables-={'worker_status'}
        if set(manifest["counts"]) != expected_tables or not isinstance(manifest["owners"], list):
            raise ValueError()
        if any(type(n) is not int or n < 0 for n in manifest["counts"].values()):
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{64}", manifest["database_scope"]):
            raise ValueError()
        if any(not isinstance(v, str) or not 1 <= len(v) <= 64 for v in manifest["owners"]):
            raise ValueError()
        if hashlib.sha256(dump).hexdigest() != manifest["dump_sha256"] or not dump.startswith(b"PGDMP"):
            raise ValueError()
        if datetime.fromisoformat(manifest["created_at"]).tzinfo is None:
            raise ValueError()
        return manifest, dump
    except (ValueError, KeyError, TypeError, struct.error):
        raise RecoveryError("archive_manifest_invalid") from None


def inspect_backup(path, key):
    manifest, _ = _unpack(path, key)
    return {k: manifest[k] for k in ("created_at", "schema_revision", "counts", "dump_sha256", "database_scope")}


def create_backup(database_url, directory, key, pg_bin, ledger, *, now=None):
    _key(key)
    read_ledger(ledger, key)
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise RecoveryError("aware_time_required")
    factory = sessions(database_url)
    engine = factory.kw["bind"]
    try:
        # Counts and pg_dump share the SAME MVCC snapshot even with concurrent writes.
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
                if revision != SCHEMA:
                    raise RecoveryError("schema_revision_unsupported")
                counts = {name: conn.scalar(text(f'SELECT count(*) FROM "{name}"')) for name in TABLES}
                owners = list(conn.scalars(text("SELECT id FROM profiles ORDER BY id")))
                token = conn.scalar(text("SELECT pg_export_snapshot()"))
                dump = _run(pg_bin, "pg_dump", ["--format=custom", "--no-owner", "--no-acl", "--schema=public",
                                               "--no-password", "--snapshot=" + token], database_url)
        manifest = dict(version=1, schema_revision=revision, created_at=now.astimezone(UTC).isoformat(), database_scope=database_scope(database_url),
                        counts=counts, owners=owners, dump_sha256=hashlib.sha256(dump).hexdigest())
        encoded = json.dumps(manifest, separators=(",", ":")).encode()
        encrypted = seal(struct.pack("!I", len(encoded)) + encoded + dump, key, "backup")
        if len(encrypted) > MAX_BYTES:
            raise RecoveryError("archive_too_large")
        path = Path(directory) / (now.astimezone(UTC).strftime("crm-%Y%m%dT%H%M%SZ-") + uuid4().hex[:12] + ".crmb")
        _write(path, encrypted)
        inspect_backup(path, key)  # Read/authenticate before considering any retention.
        removed = 0
        for old in Path(directory).iterdir():
            if old == path or old.is_symlink() or not ARCHIVE_NAME.fullmatch(old.name):
                continue
            try:
                report = inspect_backup(old, key)
            except RecoveryError:
                continue  # Never remove corrupt/unrelated/key-rotated files automatically.
            if report["database_scope"] == manifest["database_scope"] and datetime.fromisoformat(report["created_at"]) < now - timedelta(days=30):
                old.unlink()
                removed += 1
        return dict(status="backed_up", file=path.name, counts=counts, removed=removed)
    finally:
        engine.dispose()


def _target(url):
    value = make_url(url)
    _pg_env(url)
    if not re.fullmatch(r"personal_crm_(?:test_)?restore_[a-z0-9_]+", value.database or ""):
        raise RecoveryError("restore_target_name_forbidden")


def _erase_sql(owner):
    literal = sql.Literal(owner).as_string()
    statements = []
    for table in reversed(Base.metadata.sorted_tables):
        if "owner_id" in table.c:
            condition = f"owner_id={literal}"
        elif table.name == "source_versions":
            condition = f"source_id IN (SELECT id FROM sources WHERE owner_id={literal})"
        elif table.name == "profiles":
            condition = f"id={literal}"
        else:
            raise RecoveryError("erasure_schema_unsupported")
        statements.append(f'DELETE FROM "{table.name}" WHERE {condition};')
    return "\n".join(statements)


QUARANTINE = """
UPDATE profiles SET recovery_hold=true, ai_paused=true;
UPDATE web_sessions SET revoked=true;
UPDATE worker_status SET state='disabled',error_code='restore_hold',last_success_at=NULL;
UPDATE jobs SET status='cancelled', cancel_reason='restore_hold', lease_token=NULL, lease_until=NULL
 WHERE status IN ('pending','leased');
UPDATE delivery_attempts SET outcome='unknown' WHERE outcome='pending';
UPDATE ai_reservations SET status='unknown', error_code='restore_hold' WHERE status='reserved';
UPDATE source_versions SET status='processed', error_code='restore_hold', parse_token=NULL,
 parse_until=NULL, retry_at=NULL, result='{"status":"restore_review_required"}'
 WHERE status <> 'processed';
UPDATE reminders SET active=false;
UPDATE recurrences SET status='stopped';
UPDATE mail_accounts SET enabled=false,status='disabled',lease_token=NULL,lease_until=NULL,next_sync_at=NULL;
"""


def restore_backup(path, key, target_url, pg_bin, ledger):
    with ledger_lock(ledger):
        return _restore_backup(path, key, target_url, pg_bin, ledger)


def _restore_backup(path, key, target_url, pg_bin, ledger):
    _target(target_url)
    manifest, dump = _unpack(path, key)
    erased = read_ledger(ledger, key)["erased"]  # Required current external ledger, never the old backup's copy.
    factory = sessions(target_url)
    try:
        with factory() as s:
            if s.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                             "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                             "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%'")):
                raise RecoveryError("restore_target_not_empty")
        script = _run(pg_bin, "pg_restore", ["--file=-", "--no-owner", "--no-acl"], data=dump)
        checks = []
        for name, count in manifest["counts"].items():
            checks.append(f"IF (SELECT count(*) FROM \"{name}\") <> {count} THEN RAISE EXCEPTION 'restore_count_mismatch'; END IF;")
        deleted = [owner for owner in manifest["owners"] if owner_hash(owner) in erased]
        upgrade=''
        if manifest['schema_revision']!=SCHEMA:
            from sqlalchemy.schema import CreateTable,CreateIndex
            from sqlalchemy.dialects.postgresql import dialect
            names=('web_sessions','login_throttles','worker_status') if manifest['schema_revision']=='ca294b816edf' else ('worker_status',)
            for name in names:
                table=Base.metadata.tables[name]
                upgrade+=str(CreateTable(table).compile(dialect=dialect()))+';\n'
                for index in table.indexes:
                    upgrade+=str(CreateIndex(index).compile(dialect=dialect()))+';\n'
            upgrade+=f"UPDATE alembic_version SET version_num='{SCHEMA}';\n"
        tail = "\nSET search_path TO public, pg_catalog;\n"+upgrade+"DO $$ BEGIN " + " ".join(checks) + " END $$;\n" + QUARANTINE
        tail += "\n".join(_erase_sql(owner) for owner in deleted)
        # Schema, records, count verification, erasures and fencing commit together.
        _run(pg_bin, "psql", ["--no-psqlrc", "--no-password", "--single-transaction", "--set=ON_ERROR_STOP=on"],
             target_url, b"DROP SCHEMA IF EXISTS public;\n" + script + tail.encode("utf-8"))
        return dict(status="restored_on_hold", counts=manifest["counts"], erased_profiles=len(deleted))
    finally:
        factory.kw["bind"].dispose()


def erase_owner(database_url, owner, ledger, key):
    """Offline maintenance only, services stopped; journal is durable BEFORE deletion."""
    with ledger_lock(ledger):
        value = read_ledger(ledger, key)
        digest = owner_hash(owner)
        if digest not in value["erased"]:
            value["erased"].append(digest)
            _write(ledger, seal(json.dumps(value).encode(), key, "ledger"), replace=True)
        factory = sessions(database_url)
        try:
            with factory.begin() as s:
                from .models import Source
                for table in reversed(Base.metadata.sorted_tables):
                    if "owner_id" in table.c:
                        condition = table.c.owner_id == owner
                    elif table.name == "source_versions":
                        condition = table.c.source_id.in_(select(Source.id).where(Source.owner_id == owner))
                    elif table.name == "profiles":
                        condition = table.c.id == owner
                    else:
                        raise RecoveryError("erasure_schema_unsupported")
                    s.execute(table.delete().where(condition))
        finally:
            factory.kw["bind"].dispose()


def release_hold(database_url, owner, ledger, key):
    with ledger_lock(ledger):
        return _release_hold(database_url, owner, ledger, key)


def _release_hold(database_url, owner, ledger, key):
    _target(database_url)
    if owner_hash(owner) in read_ledger(ledger, key)["erased"]:
        raise RecoveryError("owner_erased")
    factory = sessions(database_url)
    try:
        with factory.begin() as s:
            changed = s.execute(text("UPDATE profiles SET recovery_hold=false WHERE id=:owner AND recovery_hold=true"), {"owner": owner})
            if changed.rowcount != 1:
                raise RecoveryError("held_owner_not_found")
    finally:
        factory.kw["bind"].dispose()


def export_owner(factory, owner):
    """User data only, a consistent snapshot; no queue leases or configuration secrets."""
    records = {}
    included = {"profiles", "tasks", "projects", "recurrences", "recurrence_history", "planning_suggestions",
                "sources", "source_versions", "proposals", "history", "reminders", "dialogues"}
    from .models import Source
    with factory.kw["bind"].connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if not conn.scalar(text("SELECT id FROM profiles WHERE id=:owner"), {"owner": owner}):
                raise RecoveryError("owner_not_found")
            for table in Base.metadata.sorted_tables:
                if table.name not in included:
                    continue
                if table.name == "profiles":
                    condition = table.c.id == owner
                elif table.name == "source_versions":
                    condition = table.c.source_id.in_(select(Source.id).where(Source.owner_id == owner))
                else:
                    condition = table.c.owner_id == owner
                rows = conn.execute(select(table).where(condition)).mappings()
                records[table.name] = [{k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.items()} for row in rows]
    return dict(version=1, exported_at=datetime.now(UTC).isoformat(), records=records)


@dataclass(frozen=True)
class BackupConfig:
    database_url: str = field(default="", repr=False)
    directory: Path = Path(".runtime/backups")
    pg_bin: Path = Path("/usr/bin")
    key: str = field(default="", repr=False)
    ledger: Path = Path(".runtime/erasures.crme")
    enabled: bool = False
    external_target_confirmed: bool = False

    @classmethod
    def from_env(cls):
        return cls(database_url=os.getenv("CRM_DATABASE_URL", ""),
                   directory=Path(os.getenv("CRM_BACKUP_DIRECTORY", ".runtime/backups")),
                   pg_bin=Path(os.getenv("CRM_PG_BIN", "/usr/bin")), key=os.getenv("CRM_BACKUP_KEY", ""),
                   ledger=Path(os.getenv("CRM_ERASURE_LEDGER", ".runtime/erasures.crme")),
                   enabled=os.getenv("CRM_BACKUP_ENABLED", "false").lower() == "true",
                   external_target_confirmed=os.getenv("CRM_BACKUP_EXTERNAL_TARGET_CONFIRMED", "false").lower() == "true")


def backup_cycle(config, *, now=None):
    if not config.enabled:
        return {"status": "disabled"}
    if not config.external_target_confirmed:
        raise RecoveryError("external_backup_target_unconfirmed")
    now = now or datetime.now(UTC)
    read_ledger(config.ledger, config.key)
    latest = None
    for path in config.directory.iterdir():
        if path.is_symlink() or not ARCHIVE_NAME.fullmatch(path.name):
            continue
        try:
            report = inspect_backup(path, config.key)
            created = datetime.fromisoformat(report["created_at"])
            if report["database_scope"] != database_scope(config.database_url):
                continue
        except RecoveryError:
            continue
        if created > now + timedelta(minutes=5):
            raise RecoveryError("backup_clock_conflict")
        latest = max(latest, created) if latest else created
    if latest and now - latest < timedelta(hours=24):
        return {"status": "not_due", "last_verified_at": latest.isoformat()}
    return create_backup(config.database_url, config.directory, config.key, config.pg_bin, config.ledger, now=now)
