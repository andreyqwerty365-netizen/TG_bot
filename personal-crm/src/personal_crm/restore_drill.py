"""Read-only remote backup download and recovery into a separate disposable stack."""
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import make_url, text

from .db import sessions
from .legacy_backup import download_restore
from .recovery import BackupConfig, RecoveryError, _write, restore_backup
from .remote_backup import RemoteBackup, S3Config


def guard_target(url):
    try:
        target = make_url(url)
        if (target.drivername != 'postgresql+psycopg' or target.host != 'restore-db'
                or target.username != 'drill' or target.database != 'personal_crm_restore_drill'
                or target.port not in (None, 5432) or target.query):
            raise ValueError()
    except Exception:
        raise RecoveryError('drill_target_forbidden') from None


def fresh(value, now):
    try:
        created = datetime.fromisoformat(value)
        if created.tzinfo is None or not -timedelta(minutes=5) <= now-created <= timedelta(hours=30):
            raise ValueError()
    except (TypeError, ValueError):
        raise RecoveryError('drill_backup_not_fresh') from None


def check_crm(worker, target_url, scratch, *, now=None, restore=restore_backup):
    guard_target(target_url)
    now = now or datetime.now(UTC)
    scratch = Path(scratch)
    scratch.mkdir(mode=0o700)
    downloaded = worker.download(scratch)
    manifest = worker.manifest
    fresh(manifest['created_at'], now)
    result = restore(scratch/downloaded['file'], worker.backup.key, target_url,
                     worker.backup.pg_bin, scratch/downloaded['ledger'])
    if result['status'] != 'restored_on_hold':
        raise RecoveryError('drill_restore_not_verified')
    return {'status': 'verified', 'backup_created_at': manifest['created_at']}


def check_legacy(remote, key, scratch, *, now=None, store=None):
    # Existing restore verifies authenticated integrity/schema/row fingerprints of BOTH SQLite files.
    result = download_restore(remote, key, scratch, store=store)
    fresh(result['created_at'], now or datetime.now(UTC))
    return {'status': 'verified', 'backup_created_at': result['created_at']}


def run_checks(crm, legacy, *, now=None):
    now = now or datetime.now(UTC)
    components = {}
    for name, call in [('crm', crm), ('legacy', legacy)]:
        try:
            components[name] = call()
        except Exception:
            # Never publish exception text, keys, paths, table names or restored contents.
            components[name] = {'status': 'failed', 'code': 'restore_check_failed'}
    success = all(item['status'] == 'verified' for item in components.values())
    return {'version': 1, 'status': 'verified' if success else 'failed',
            'completed_at': now.isoformat(), 'components': components}


def verify_quarantine(url):
    factory = sessions(url)
    try:
        with factory() as s:
            for query in ('SELECT count(*) FROM profiles WHERE NOT recovery_hold',
                          'SELECT count(*) FROM reminders WHERE active',
                          'SELECT count(*) FROM web_sessions WHERE NOT revoked',
                          "SELECT count(*) FROM jobs WHERE status IN ('pending','leased')"):
                if s.scalar(text(query)):
                    raise RecoveryError('drill_restore_not_fenced')
    finally:
        factory.kw['bind'].dispose()


def main():
    report_path = Path(os.getenv('OPS_RESTORE_REPORT', '/reports/restore-last-run.json'))
    try:
        if os.getenv('OPS_RESTORE_CONFIRMED') != 'true':
            raise RecoveryError('drill_not_confirmed')
        target = os.environ['OPS_RESTORE_DATABASE_URL']
        guard_target(target)
        backup = BackupConfig.from_env()
        worker = RemoteBackup(backup, S3Config.from_env(), '')
        legacy = S3Config(True, os.environ['LEGACY_S3_ENDPOINT'], os.environ['LEGACY_S3_BUCKET'],
                          os.environ['LEGACY_S3_ACCESS_KEY'], os.environ['LEGACY_S3_SECRET_KEY'],
                          os.getenv('LEGACY_S3_REGION', 'default'), os.getenv('LEGACY_S3_PREFIX', 'legacy-bot'))
        key = Path(os.environ['LEGACY_BACKUP_KEY_FILE']).read_text().strip()
        with TemporaryDirectory(prefix='crm-restore-drill-') as scratch:
            now = datetime.now(UTC)
            def crm():
                result = check_crm(worker, target, Path(scratch)/'crm', now=now)
                verify_quarantine(target)
                return result
            result = run_checks(crm, lambda: check_legacy(legacy, key, Path(scratch)/'legacy', now=now), now=now)
    except Exception:
        result = {'version': 1, 'status': 'failed', 'completed_at': datetime.now(UTC).isoformat(),
                  'components': {}, 'code': 'restore_setup_failed'}
    _write(report_path, json.dumps(result, sort_keys=True).encode(), replace=True)
    if result['status'] == 'verified':
        _write(report_path.with_name('restore-last-success.json'), json.dumps(result, sort_keys=True).encode(), replace=True)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
