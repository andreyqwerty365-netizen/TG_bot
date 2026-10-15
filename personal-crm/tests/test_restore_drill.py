import importlib
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import text

from personal_crm.recovery import RecoveryError, restore_backup
from test_remote_backup import SyntheticStore, configs
from test_recovery import OWNER, pg_bin, target
from test_legacy_backup import source


def module():
    return importlib.import_module('personal_crm.restore_drill')


@pytest.mark.parametrize('target_url',[
    'postgresql+psycopg://drill@db/personal_crm_restore_drill',
    'postgresql+psycopg://drill@restore-db/personal_crm',
    'postgresql+psycopg://crm@restore-db/personal_crm_restore_drill',
    'postgresql+psycopg://drill@127.0.0.1/personal_crm_restore_drill',
])
def test_target_refuses_any_live_or_unexpected_destination(target_url):
    with pytest.raises(RecoveryError,match='drill_target_forbidden'):
        module().guard_target(target_url)


def test_target_allows_only_the_separate_compose_database():
    module().guard_target('postgresql+psycopg://drill:synthetic@restore-db:5432/personal_crm_restore_drill')


def test_backup_age_rejects_stale_future_and_naive(clock):
    for value in [clock.now-timedelta(hours=31),clock.now+timedelta(minutes=10),clock.now.replace(tzinfo=None)]:
        with pytest.raises(RecoveryError,match='drill_backup_not_fresh'):
            module().fresh(value.isoformat(),clock.now)


def test_crm_drill_downloads_and_restores_real_postgres_with_current_ledger(factory,service,clock,tmp_path,pg_bin,target):
    from personal_crm.remote_backup import RemoteBackup
    remote_module=importlib.import_module('personal_crm.remote_backup')
    backup,remote=configs(remote_module,tmp_path,pg_bin)
    store=SyntheticStore()
    worker=RemoteBackup(backup,remote,OWNER,store=store)
    worker.tick(now=clock.now)
    def isolated_restore(path,key,target_url,bin_path,ledger):
        assert target_url=='postgresql+psycopg://drill:synthetic@restore-db/personal_crm_restore_drill'
        return restore_backup(path,key,target,bin_path,ledger)
    result=module().check_crm(worker,'postgresql+psycopg://drill:synthetic@restore-db/personal_crm_restore_drill',tmp_path/'drill',now=clock.now,restore=isolated_restore)
    assert result=={'status':'verified','backup_created_at':clock.now.isoformat()}
    from personal_crm.db import sessions
    with sessions(target)() as s:
        assert s.scalar(text('SELECT count(*) FROM profiles WHERE recovery_hold'))==1
        assert s.scalar(text('SELECT count(*) FROM reminders WHERE active'))==0


def test_crm_drill_rejects_stale_backup_before_restore(factory,service,clock,tmp_path,pg_bin):
    from personal_crm.remote_backup import RemoteBackup
    backup,remote=configs(importlib.import_module('personal_crm.remote_backup'),tmp_path,pg_bin)
    worker=RemoteBackup(backup,remote,OWNER,store=SyntheticStore());worker.tick(now=clock.now)
    def must_not_restore(*args):
        pytest.fail('stale archive must not be restored')
    with pytest.raises(RecoveryError,match='drill_backup_not_fresh'):
        module().check_crm(worker,'postgresql+psycopg://drill:synthetic@restore-db/personal_crm_restore_drill',tmp_path/'stale',now=clock.now+timedelta(hours=31),restore=must_not_restore)


def test_components_are_independent_and_reports_never_contain_private_errors(clock):
    def bad():raise RuntimeError('private DSN token bucket')
    calls=[]
    def good():calls.append(True);return {'status':'verified','backup_created_at':clock.now.isoformat()}
    report=module().run_checks(bad,good,now=clock.now)
    assert report['status']=='failed'
    assert report['components']['crm']=={'status':'failed','code':'restore_check_failed'}
    assert report['components']['legacy']['status']=='verified'
    assert calls==[True]
    assert 'private' not in str(report)


def test_legacy_drill_restores_both_databases_and_rejects_stale_archive(source,tmp_path):
    from test_legacy_backup import Store,REMOTE,KEY,NOW
    from personal_crm.legacy_backup import run_backup
    store=Store();run_backup(source,tmp_path/'archives',KEY,REMOTE,store=store,now=NOW)
    result=module().check_legacy(REMOTE,KEY,tmp_path/'restore',store=store,now=NOW)
    assert result=={'status':'verified','backup_created_at':NOW.isoformat()}
    assert (tmp_path/'restore'/'notes.db').is_file()
    assert (tmp_path/'restore'/'workouts.sqlite3').is_file()
    with pytest.raises(RecoveryError,match='drill_backup_not_fresh'):
        module().check_legacy(REMOTE,KEY,tmp_path/'stale',store=store,now=NOW+timedelta(hours=31))
