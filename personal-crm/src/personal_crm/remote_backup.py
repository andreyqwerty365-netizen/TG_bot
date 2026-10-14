"""Verified encrypted S3 publication; disabled until explicitly configured."""
import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass,field
from datetime import UTC,datetime,timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.exc import SQLAlchemyError

from .db import sessions
from .operations import record
from .recovery import (ARCHIVE_NAME,MAX_BYTES,BackupConfig,RecoveryError,create_backup,database_scope,
                       decode_archive,ledger_lock,read_ledger,seal,unseal,_write)


@dataclass(frozen=True)
class S3Config:
    enabled: bool=False
    endpoint: str=''
    bucket: str=''
    access_key: str=field(default='',repr=False)
    secret_key: str=field(default='',repr=False)
    region: str='ru-1'
    prefix: str='personal-crm'

    @classmethod
    def from_env(cls):
        return cls(os.getenv('CRM_S3_ENABLED','false').lower()=='true',os.getenv('CRM_S3_ENDPOINT',''),
                   os.getenv('CRM_S3_BUCKET',''),os.getenv('CRM_S3_ACCESS_KEY',''),os.getenv('CRM_S3_SECRET_KEY',''),
                   os.getenv('CRM_S3_REGION','ru-1'),os.getenv('CRM_S3_PREFIX','personal-crm'))


def validate(config):
    endpoint=urlsplit(config.endpoint)
    if (not config.enabled or endpoint.scheme!='https' or not endpoint.hostname or endpoint.username or endpoint.password
        or endpoint.query or endpoint.fragment or endpoint.path not in ('','/')
        or not config.bucket or not config.access_key or not config.secret_key
        or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',config.prefix)):
        raise RecoveryError('s3_configuration_invalid')


class S3Store:
    def __init__(self,config):
        validate(config)
        import boto3
        from botocore.config import Config
        self.bucket=config.bucket
        self.client=boto3.session.Session(aws_access_key_id=config.access_key,aws_secret_access_key=config.secret_key,
            region_name=config.region).client('s3',endpoint_url=config.endpoint,
                config=Config(connect_timeout=5,read_timeout=15,retries={'mode':'standard','total_max_attempts':2},
                              s3={'addressing_style':'path'},max_pool_connections=2))

    def put(self,key,value):
        self.client.put_object(Bucket=self.bucket,Key=key,Body=value,ContentType='application/octet-stream')

    def get(self,key):
        from botocore.exceptions import ClientError
        try:
            response=self.client.get_object(Bucket=self.bucket,Key=key)
        except ClientError as error:
            if error.response.get('Error',{}).get('Code') in ('NoSuchKey','404','NotFound'):
                return None
            raise
        body=response['Body']
        try:
            value=body.read(MAX_BYTES+1)
        finally:
            body.close()
        if len(value)>MAX_BYTES:
            raise RecoveryError('archive_too_large')
        return value

    def keys(self,prefix):
        result=[]
        for page in self.client.get_paginator('list_objects_v2').paginate(Bucket=self.bucket,Prefix=prefix,
                PaginationConfig={'PageSize':100}):
            result.extend(item['Key'] for item in page.get('Contents',[]))
            if len(result)>1000:
                raise RecoveryError('remote_catalog_limit')
        return result

    def delete(self,key):
        self.client.delete_object(Bucket=self.bucket,Key=key)


class RemoteBackup:
    def __init__(self,backup,remote,owner,*,store=None):
        self.backup,self.remote,self.owner=backup,remote,owner
        self.store=store
        self.last_head=None
        self.manifest=None

    def _call(self,method,*args):
        try:
            return getattr(self.store,method)(*args)
        except RecoveryError:
            raise
        except Exception:
            # Provider diagnostics can contain credentials, bucket names and private paths.
            raise RecoveryError('remote_storage_failed') from None

    def _document(self,value,purpose):
        try:
            if not isinstance(value,bytes):
                raise ValueError()
            data=json.loads(unseal(value,self.backup.key,purpose))
            if not isinstance(data,dict) or data.get('version')!=1:
                raise ValueError()
            return data
        except (ValueError,TypeError):
            raise RecoveryError('remote_manifest_invalid') from None

    def _root(self):
        return self.remote.prefix+'/'+database_scope(self.backup.database_url)+'/'

    def _publish(self,key,value):
        self._call('put',key,value)
        if self._call('get',key)!=value:
            raise RecoveryError('remote_verification_failed')

    def _ledger(self,root,head_exists):
        local=read_ledger(self.backup.ledger,self.backup.key)
        marker=self._call('get',root+'ledger-head.crme')
        if marker:
            info=self._document(marker,'ledger-head')
            digest=info.get('sha256','')
            if not re.fullmatch(r'[a-f0-9]{64}',digest):
                raise RecoveryError('remote_manifest_invalid')
            value=self._call('get',root+'ledgers/'+digest+'.crme')
            if not value or hashlib.sha256(value).hexdigest()!=digest:
                raise RecoveryError('remote_ledger_missing')
            previous=self._document(value,'ledger')
            if not set(previous.get('erased',[])).issubset(set(local['erased'])):
                raise RecoveryError('remote_ledger_conflict')
        elif head_exists:
            raise RecoveryError('remote_ledger_missing')
        value=Path(self.backup.ledger).read_bytes()
        digest=hashlib.sha256(value).hexdigest()
        if marker and info['sha256']==digest:
            return
        self._publish(root+'ledgers/'+digest+'.crme',value)
        self._publish(root+'ledger-head.crme',seal(json.dumps({'version':1,'sha256':digest}).encode(),self.backup.key,'ledger-head'))

    def _head(self,root):
        value=self._call('get',root+'archive-head.crme')
        if value is None:
            return None
        info=self._document(value,'remote-head')
        if info.get('scope')!=database_scope(self.backup.database_url) or not ARCHIVE_NAME.fullmatch(info.get('archive','')):
            raise RecoveryError('remote_manifest_invalid')
        if value!=self.last_head:
            raw=self._call('get',root+'archives/'+info['archive'])
            if not raw:
                raise RecoveryError('remote_archive_missing')
            manifest,_=decode_archive(raw,self.backup.key)
            if (manifest['dump_sha256']!=info.get('dump_sha256') or manifest['database_scope']!=info['scope']
                or manifest['created_at']!=info.get('created_at')):
                raise RecoveryError('remote_verification_failed')
            self.manifest=manifest
            self.last_head=value
        return self.manifest

    def tick(self,*,now=None):
        if not self.backup.enabled or not self.remote.enabled:
            return {'status':'disabled'}
        validate(self.remote)
        if not self.backup.external_target_confirmed or not self.owner:
            raise RecoveryError('external_backup_target_unconfirmed')
        if self.store is None:
            self.store=S3Store(self.remote)
        now=now or datetime.now(UTC)
        factory=sessions(self.backup.database_url)
        try:
            record(factory,self.owner,'backup','running',now=now)
            with ledger_lock(self.backup.ledger):
                root=self._root()
                manifest=self._head(root)
                self._ledger(root,manifest is not None)
                if manifest:
                    created=datetime.fromisoformat(manifest['created_at'])
                    if created>now+timedelta(minutes=5):
                        raise RecoveryError('backup_clock_conflict')
                    if now-created<timedelta(hours=24):
                        record(factory,self.owner,'backup','idle',now=now,success_at=created)
                        return {'status':'not_due','last_verified_at':created.isoformat()}
                report=create_backup(self.backup.database_url,self.backup.directory,self.backup.key,self.backup.pg_bin,self.backup.ledger,now=now)
                value=(self.backup.directory/report['file']).read_bytes()
                manifest,_=decode_archive(value,self.backup.key)
                self._publish(root+'archives/'+report['file'],value)
                info=dict(version=1,scope=manifest['database_scope'],archive=report['file'],
                          created_at=manifest['created_at'],dump_sha256=manifest['dump_sha256'])
                self._publish(root+'archive-head.crme',seal(json.dumps(info).encode(),self.backup.key,'remote-head'))
                self.last_head=None
                self._head(root)
                record(factory,self.owner,'backup','idle',now=now,success_at=now)
                for key in self._call('keys',root+'archives/'):
                    name=key.removeprefix(root+'archives/')
                    if not ARCHIVE_NAME.fullmatch(name) or name==report['file']:
                        continue
                    try:
                        old,_=decode_archive(self._call('get',key),self.backup.key)
                    except (RecoveryError,TypeError):
                        continue
                    if old['database_scope']==manifest['database_scope'] and datetime.fromisoformat(old['created_at'])<now-timedelta(days=30):
                        self._call('delete',key)
                return {'status':'verified_remote','file':report['file']}
        except RecoveryError:
            try:
                record(factory,self.owner,'backup','error',error_code='backup_unavailable',now=now)
            except SQLAlchemyError:
                pass
            raise
        finally:
            factory.kw['bind'].dispose()

    def download(self,directory):
        validate(self.remote)
        if self.store is None:
            self.store=S3Store(self.remote)
        root=self._root();manifest=self._head(root)
        if not manifest:
            raise RecoveryError('remote_archive_missing')
        head=self._call('get',root+'archive-head.crme')
        if head!=self.last_head:
            raise RecoveryError('remote_verification_failed')
        info=self._document(head,'remote-head')
        marker=self._call('get',root+'ledger-head.crme')
        if not marker:
            raise RecoveryError('remote_ledger_missing')
        digest=self._document(marker,'ledger-head').get('sha256','')
        if not re.fullmatch(r'[a-f0-9]{64}',digest):
            raise RecoveryError('remote_manifest_invalid')
        ledger=self._call('get',root+'ledgers/'+digest+'.crme')
        if not ledger or hashlib.sha256(ledger).hexdigest()!=digest:
            raise RecoveryError('remote_ledger_missing')
        self._document(ledger,'ledger')
        archive=self._call('get',root+'archives/'+info['archive'])
        if not archive:
            raise RecoveryError('remote_archive_missing')
        actual,_=decode_archive(archive,self.backup.key)
        if actual!=manifest:
            raise RecoveryError('remote_verification_failed')
        destination=Path(directory)
        if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
            raise RecoveryError('download_directory_not_empty')
        _write(destination/info['archive'],archive)
        _write(Path(directory)/'erasures.crme',ledger)
        return {'status':'downloaded_verified','file':info['archive'],'ledger':'erasures.crme'}


def main():
    parser=argparse.ArgumentParser(description='Opt-in verified encrypted S3 backups')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--download',type=Path)
    args=parser.parse_args()
    worker=RemoteBackup(BackupConfig.from_env(),S3Config.from_env(),os.getenv('CRM_OWNER_ID',''))
    while True:
        try:
            result=worker.download(args.download) if args.download else worker.tick()
            if args.once or args.download or result['status'] in ('disabled','verified_remote'):
                print(json.dumps(result),flush=True)
            if args.once or args.download or result['status']=='disabled':
                return
        except (RecoveryError,SQLAlchemyError,OSError,ValueError) as error:
            print(json.dumps({'status':'error','code':str(error) if isinstance(error,RecoveryError) else 'backup_unavailable'}),flush=True)
            if args.once or args.download:
                raise SystemExit(1) from None
        time.sleep(60)


if __name__=='__main__':
    main()
