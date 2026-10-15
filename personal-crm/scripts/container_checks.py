"""Synthetic Linux Docker rehearsal: actual production image, Caddy TLS, restart and restore."""
import argparse
import base64
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from argon2 import PasswordHasher

ROOT=Path(__file__).resolve().parents[1]


def guard(project,runtime):
    match=re.fullmatch(r'crm-check-([a-f0-9]{6,16})',project)
    expected=(ROOT/'.runtime'/('container-ci-'+match[1])).resolve() if match else None
    if (not match or Path(runtime).resolve()!=expected or (ROOT/'.runtime').is_symlink()
        or Path(runtime).is_symlink()):raise ValueError('owned_rehearsal_project_required')


def local_daemon(endpoint):
    if endpoint not in ('unix:///var/run/docker.sock','npipe:////./pipe/docker_engine'):
        raise ValueError('local_docker_daemon_required')


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));return listener.getsockname()[1]


def run():
    if os.name=='nt':raise ValueError('linux_docker_required')
    suffix=secrets.token_hex(6);project='crm-check-'+suffix;runtime=ROOT/'.runtime'/('container-ci-'+suffix)
    guard(project,runtime);runtime.mkdir(parents=True)
    config=runtime/'config';config.mkdir(mode=0o700)
    for name in ('backups','ledger'):(runtime/name).mkdir(mode=0o700)
    env={k:v for k,v in os.environ.items() if not k.upper().startswith(('CRM_','OPENAI_','BOT_','PG','DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS'))}
    password='synthetic-'+secrets.token_urlsafe(24);db_password=secrets.token_hex(20)
    https_port,http_port=free_port(),free_port()
    while http_port==https_port:http_port=free_port()
    origin=f'https://localhost:{https_port}';url=f'postgresql+psycopg://crm:{db_password}@db:5432/personal_crm'
    env.update(CRM_IMAGE='personal-crm:check-'+suffix,CRM_BACKUP_IMAGE='personal-crm-backup:check-'+suffix,
        CRM_HOST='localhost',ACME_EMAIL='synthetic@example.invalid',CRM_CONFIG_DIRECTORY=str(config),
        CRM_DATA_DIRECTORY=str(runtime),CRM_CI_HTTPS_PORT=str(https_port),CRM_CI_HTTP_PORT=str(http_port))
    files={
        'db-password':db_password+'\n','database.env':'CRM_DATABASE_URL='+url+'\n',
        'identity.env':'CRM_OWNER_ID=synthetic-container-ci\nCRM_TIMEZONE=Europe/Moscow\n',
        'web.env':'CRM_WEB_PASSWORD_HASH='+PasswordHasher().hash(password)+'\nCRM_WEB_ORIGIN='+origin+
            '\nCRM_OWNER_TOKEN=\nCRM_BACKUP_ENABLED=false\nCRM_S3_ENABLED=false\nCRM_TELEGRAM_SEND_ENABLED=false\n',
        'ingress.env':'CRM_TELEGRAM_WEBHOOK_ENABLED=false\n','delivery.env':'CRM_TELEGRAM_SEND_ENABLED=false\n',
        'backup.env':'CRM_BACKUP_ENABLED=false\nCRM_BACKUP_EXTERNAL_TARGET_CONFIRMED=false\nCRM_S3_ENABLED=false\nCRM_BACKUP_KEY='+
            base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()+'\n',
    }
    for name,content in files.items():
        descriptor=os.open(config/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:stream.write(content)
    compose=['docker','compose','-p',project,'-f','compose.production.yaml','-f','compose.ci.yaml','--profile','backup']
    with (runtime/'commands.log').open('w',encoding='utf-8') as log:
        def command(args,*,timeout=180,check=True):
            result=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
            log.write(result.stdout+result.stderr);log.flush()
            if check:result.check_returncode()
            return result.stdout.strip()
        endpoint=command(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}'])
        local_daemon(endpoint)
        touched=False
        try:
            command(['docker','build','-f','Dockerfile.production','--target','runtime','-t',env['CRM_IMAGE'],'.'],timeout=1200)
            command(['docker','build','-f','Dockerfile.production','--target','backup','-t',env['CRM_BACKUP_IMAGE'],'.'],timeout=1200)
            images={name:command(['docker','image','inspect',env[key],'--format','{{.Id}}'])
                    for name,key in [('runtime','CRM_IMAGE'),('backup','CRM_BACKUP_IMAGE')]}
            runtime_python=command(['docker','run','--rm',env['CRM_IMAGE'],'python','--version'])
            # Host bind directories belong to this generated laboratory only.
            command(['docker','run','--rm','--user','0:0','--mount',f'type=bind,source={runtime},target=/lab',
                env['CRM_IMAGE'],'python','-c',"import os; [os.chown('/lab/'+n,10002,10002) for n in ('backups','ledger')]"])
            command([*compose,'config','--quiet']);touched=True
            command([*compose,'up','-d','--wait','db'])
            command([*compose,'run','--rm','migrate'])
            command([*compose,'run','--rm','--no-deps','api','python','-m','personal_crm.pilot_setup','initialize-owner'])
            command([*compose,'run','--rm','--no-deps','backup','python','-m','personal_crm.maintenance','init-ledger'])
            command([*compose,'up','-d','api','source','caddy'])
            ca=runtime/'root.crt';deadline=time.monotonic()+90
            while not ca.exists():
                command([*compose,'cp','caddy:/data/caddy/pki/authorities/local/root.crt',str(ca)],check=False)
                if time.monotonic()>deadline:raise RuntimeError('local_ca_timeout')
                if not ca.exists():time.sleep(1)
            context=ssl.create_default_context(cafile=str(ca))
            with httpx.Client(base_url=origin,verify=context,timeout=5,trust_env=False) as client:
                def ready():
                    until=time.monotonic()+90
                    while True:
                        try:
                            if client.get('/ready').status_code==200:return
                        except httpx.TransportError:pass
                        if time.monotonic()>until:raise RuntimeError('production_readiness_timeout')
                        time.sleep(1)
                ready()
                assert client.get('/app/').status_code==200
                assert client.get('/docs').status_code==client.get('/openapi.json').status_code==404
                login=client.post('/auth/login',json={'password':password},headers={'Origin':origin,
                    'X-Forwarded-Proto':'http','X-Forwarded-For':'198.51.100.99'})
                login.raise_for_status();cookie=login.headers['set-cookie']
                assert all(flag in cookie for flag in ('__Host-crm_session=','HttpOnly','Secure','SameSite=strict'))
                csrf=login.json()['csrf_token'];headers={'Origin':origin,'X-CSRF-Token':csrf}
                assert client.get('/auth/session').status_code==200
                body={'request_id':'container-ci-task','title':'Synthetic production rehearsal',
                      'reminder_local':(datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')}
                assert client.post('/workspace/tasks',json=body).status_code==403
                assert client.post('/workspace/tasks',json=body,headers={**headers,'Origin':'https://evil.example.invalid'}).status_code==403
                created=client.post('/workspace/tasks',json=body,headers=headers);created.raise_for_status();task=created.json()
                health=client.get('/workspace/system').json()
                assert health['workers']['source']['status'] in ('running','idle')
                assert health['workers']['delivery']['status']==health['backup']['status']=='disabled'
                assert health['queue']['pending']>=1 and health['queue']['sent']==0
                command([*compose,'run','--rm','--no-deps','delivery','python','-m','personal_crm.worker','--once'])
                assert client.get('/workspace/system').json()['queue']['sent']==0
                backup=json.loads(command([*compose,'run','--rm','--no-deps','backup','python','-m','personal_crm.maintenance','backup']))
                archive=backup['file'];target='personal_crm_test_restore_ci_'+suffix
                command([*compose,'exec','-T','db','createdb','-U','crm',target])
                env['CRM_RESTORE_DATABASE_URL']=url.replace('/personal_crm','/'+target)
                restored=json.loads(command([*compose,'run','--rm','--no-deps','--env','CRM_RESTORE_DATABASE_URL','backup',
                    'python','-m','personal_crm.maintenance','restore','/var/lib/crm-backup/'+archive]))
                assert restored['status']=='restored_on_hold'
                def query(database,sql):
                    return command([*compose,'exec','-T','db','psql','-U','crm','-d',database,'-tAc',sql])
                assert query(target,'SELECT count(*) FROM profiles WHERE recovery_hold')=='1'
                assert query(target,'SELECT count(*) FROM web_sessions WHERE revoked')=='1'
                assert query(target,'SELECT count(*) FROM tasks')=='1'
                assert query(target,'SELECT count(*) FROM reminders WHERE active')=='0'
                assert query(target,"SELECT count(*) FROM jobs WHERE status IN ('pending','leased')")=='0'
                command([*compose,'restart','db','api','source','caddy']);ready()
                assert client.get('/auth/session').status_code==200
                persisted=client.get('/workspace/tasks/'+task['id']);persisted.raise_for_status()
                assert persisted.json()['title']==body['title']
                assert client.get('/workspace/system').json()['queue']['pending']>=1
                client.post('/auth/logout',headers=headers).raise_for_status()
                assert client.get('/auth/session').status_code==401
            report={'status':'passed','platform':'Linux Docker','image_ids':images,
                'runtime_python':runtime_python,'postgresql_version':query('personal_crm','SHOW server_version'),
                'pg_dump_version':command([*compose,'run','--rm','--no-deps','backup','/usr/lib/postgresql/16/bin/pg_dump','--version']),
                'caddy_version':command([*compose,'exec','-T','caddy','caddy','version']),
                'https':'Caddy local CA verified without insecure TLS','session_restart':'passed',
                'csrf_origin':'passed','disabled_delivery':'passed','encrypted_local_restore':'passed',
                'not_run':['VPS reboot','public DNS/ACME','real S3','real Telegram']}
            (runtime/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))
            summary=os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary,'a',encoding='utf-8') as stream:stream.write('### CRM synthetic container rehearsal\n\n```json\n'+json.dumps(report,indent=2)+'\n```\n')
        finally:
            if touched:
                guard(project,runtime)
                command([*compose,'logs','--no-color','--tail','100'],check=False)
                command([*compose,'down','--volumes','--remove-orphans'])


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:run()
    except Exception:
        raise SystemExit('container_checks_failed; inspect only the synthetic .runtime/container-ci-*/commands.log') from None


if __name__=='__main__':main()
