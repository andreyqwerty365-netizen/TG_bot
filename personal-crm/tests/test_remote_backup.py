import importlib
import os
from dataclasses import replace
from datetime import timedelta

import pytest

from personal_crm.recovery import BackupConfig,initialize_ledger
from test_recovery import KEY,OWNER,pg_bin,target


class SyntheticStore:
    def __init__(self):
        self.values={};self.fail=False;self.corrupt=False;self.deleted=[];self.reads=0
    def put(self,key,value):
        if self.fail:raise RuntimeError('synthetic private provider error')
        self.values[key]=value
    def get(self,key):
        self.reads+=1
        value=self.values.get(key)
        if value and self.corrupt and key.endswith('.crmb'):return value[:-1]+b'x'
        return value
    def keys(self,prefix):return [k for k in self.values if k.startswith(prefix)]
    def delete(self,key):self.deleted.append(key);del self.values[key]


def configs(module,tmp_path,pg_bin):
    ledger=tmp_path/'erasures.crme';initialize_ledger(ledger,KEY)
    backup=BackupConfig(database_url=os.environ['CRM_TEST_DATABASE_URL'],directory=tmp_path,pg_bin=pg_bin,
                        key=KEY,ledger=ledger,enabled=True,external_target_confirmed=True)
    remote=module.S3Config(enabled=True,endpoint='https://s3.example.invalid',bucket='synthetic-bucket',
                           access_key='synthetic-key',secret_key='synthetic-secret')
    return backup,remote


def test_publish_reads_back_archive_and_daily_state_survives_restart(factory,service,clock,tmp_path,pg_bin):
    module=importlib.import_module('personal_crm.remote_backup')
    backup,remote=configs(module,tmp_path,pg_bin);store=SyntheticStore()
    worker=module.RemoteBackup(backup,remote,OWNER,store=store)
    result=worker.tick(now=clock.now)
    assert result['status']=='verified_remote'
    assert any(k.endswith('.crmb') for k in store.values)
    assert all(b'Synthetic task' not in v for v in store.values.values())
    restarted=module.RemoteBackup(backup,remote,OWNER,store=store)
    assert restarted.tick(now=clock.now+timedelta(hours=23))['status']=='not_due'
    assert restarted.tick(now=clock.now+timedelta(hours=24))['status']=='verified_remote'


def test_failed_upload_never_deletes_previous_remote_copy(factory,service,clock,tmp_path,pg_bin):
    module=importlib.import_module('personal_crm.remote_backup')
    backup,remote=configs(module,tmp_path,pg_bin);store=SyntheticStore();worker=module.RemoteBackup(backup,remote,OWNER,store=store)
    worker.tick(now=clock.now);before=dict(store.values);store.fail=True
    with pytest.raises(module.RecoveryError,match='remote_storage_failed'):
        worker.tick(now=clock.now+timedelta(days=31))
    assert store.values==before and store.deleted==[]


def test_corrupt_readback_is_not_reported_as_success(factory,service,clock,tmp_path,pg_bin):
    module=importlib.import_module('personal_crm.remote_backup')
    backup,remote=configs(module,tmp_path,pg_bin);store=SyntheticStore();store.corrupt=True
    with pytest.raises(module.RecoveryError):
        module.RemoteBackup(backup,remote,OWNER,store=store).tick(now=clock.now)
    from personal_crm.operations import overview
    assert overview(factory,OWNER,now=clock.now,backup_enabled=True)['backup']['status']=='missing'
    assert not any(k.endswith('head.crme') and '/archives/' not in k and 'ledger' not in k for k in store.values)


def test_retention_after_verified_copy_keeps_foreign_objects_and_ledger(factory,service,clock,tmp_path,pg_bin):
    module=importlib.import_module('personal_crm.remote_backup')
    backup,remote=configs(module,tmp_path,pg_bin);store=SyntheticStore();worker=module.RemoteBackup(backup,remote,OWNER,store=store)
    worker.tick(now=clock.now);old=[k for k in store.values if k.endswith('.crmb')][0]
    store.values['foreign/object']=b'foreign'
    worker.tick(now=clock.now+timedelta(days=31))
    assert old not in store.values and store.values['foreign/object']==b'foreign'
    assert any('/ledgers/' in k for k in store.values)


def test_s3_is_disabled_by_default_and_http_or_missing_credentials_fail_closed(tmp_path):
    module=importlib.import_module('personal_crm.remote_backup')
    worker=module.RemoteBackup(BackupConfig(),module.S3Config(),OWNER,store=SyntheticStore())
    assert worker.tick()['status']=='disabled'
    for config in [module.S3Config(enabled=True,endpoint='http://example.invalid',bucket='synthetic',access_key='key',secret_key='secret'),
                   module.S3Config(enabled=True,endpoint='https://example.invalid',bucket='synthetic')]:
        with pytest.raises(module.RecoveryError,match='s3_configuration_invalid'):
            module.S3Store(config)


def test_download_checks_the_actual_saved_bytes_and_never_overwrites(factory,service,clock,tmp_path,pg_bin,target):
    module=importlib.import_module('personal_crm.remote_backup')
    backup,remote=configs(module,tmp_path,pg_bin);store=SyntheticStore()
    worker=module.RemoteBackup(backup,remote,OWNER,store=store);worker.tick(now=clock.now)
    destination=tmp_path/'download';destination.mkdir()
    worker.download(destination)
    assert module.decode_archive(next(destination.glob('*.crmb')).read_bytes(),KEY)[0]['counts']['profiles']==1
    from personal_crm.recovery import restore_backup
    assert restore_backup(next(destination.glob('*.crmb')),KEY,target,pg_bin,destination/'erasures.crme')['status']=='restored_on_hold'
    with pytest.raises(module.RecoveryError):worker.download(destination)
    store.corrupt=True
    other=tmp_path/'corrupt';other.mkdir()
    with pytest.raises(module.RecoveryError):worker.download(other)
    assert list(other.iterdir())==[]


def test_missing_encrypted_documents_fail_with_safe_error(tmp_path):
    module=importlib.import_module('personal_crm.remote_backup')
    worker=module.RemoteBackup(BackupConfig(key=KEY),module.S3Config(),OWNER,store=SyntheticStore())
    with pytest.raises(module.RecoveryError):worker._document(None,'remote-head')


def test_sdk_reads_close_stream_and_checks_limit_without_contacting_any_account():
    import io
    from botocore.response import StreamingBody
    from botocore.stub import Stubber
    from personal_crm.remote_backup import S3Config,S3Store
    config=S3Config(True,'https://s3.example.invalid','synthetic-bucket','synthetic-key','synthetic-secret')
    store=S3Store(config);stream=io.BytesIO(b'encrypted-synthetic')
    with Stubber(store.client) as stub:
        stub.add_response('get_object',{'Body':StreamingBody(stream,19)}, {'Bucket':'synthetic-bucket','Key':'archive'})
        assert store.get('archive')==b'encrypted-synthetic'
        assert stream.closed
        stub.add_client_error('get_object',service_error_code='NoSuchKey',http_status_code=404,
                              expected_params={'Bucket':'synthetic-bucket','Key':'missing'})
        assert store.get('missing') is None
        stub.assert_no_pending_responses()
